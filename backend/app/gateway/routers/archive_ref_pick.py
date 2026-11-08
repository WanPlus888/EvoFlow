"""网关侧档案参考图优选接线：环境开关 + L1/L2 生产函数。

纯函数在 :mod:`evoflow.collab.archive_ref_picker`（harness 层，无 app 依赖）；
本模块只做三件事：

1. 读开关（阶段 E）：
   - ``FORCE_PRIMARY_IMAGE=1`` → 跳过自动，有图即 ``[0]+forced0``（回滚兜底）
   - ``ARCHIVE_REF_L1=0`` / ``ARCHIVE_REF_L2=0`` → 跳过对应层
   - ``ARCHIVE_REF_PICK_DEADLINE_MS`` → 总预算（默认 10000）
2. L1：用仓内 ``evoflow.models.openai_compat_invoke`` 做纯文本元数据选图
   （不传原图像素）。
3. L2：Vision 打分。档案图片字节本仓没有既有取图通道，需运维配置
   ``ARCHIVE_REF_IMAGE_URL_TEMPLATE``（含 ``{key}``，可选 ``{product_id}``）；
   未配置或取图失败 → L2 层失败，按设计降级（L0/L1 结果或 forced0）。
   分数缓存键 ``asset_id + image_key + model + task_kind``，命中不计费。
"""

from __future__ import annotations

import base64
import json
import logging
import os
from urllib.parse import quote

import httpx

logger = logging.getLogger("evoflow.gateway.archive_ref_pick")

_TRUTHY = {"1", "true", "yes", "on"}
_L2_SCORE_CACHE: dict[tuple, float] = {}
_L2_CACHE_MAX = 512
_L2_IMAGE_BYTES_MAX = 2 * 1024 * 1024
_L2_FETCH_TIMEOUT = 6.0

_L1_SYSTEM = (
    "你是电商商品档案参考图优选器。根据任务类型和图片元数据（仅下标/视角/主图标记，"
    "没有像素信息）选出最合适的参考图下标。只输出 JSON："
    '{"indexes": [..], "reason": "不超过80字的人话"}。'
    "主图任务优先白底/正面；细节任务优先细节/材质；视频封面优先场景/全身；"
    "视频多图要视角互补，不要选重复视角。"
)


def _flag(name: str, default_on: bool = True) -> bool:
    """显式真值（1/true/yes/on）才开；未设置用默认（L1/L2 默认开，总开关默认关）。"""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default_on
    return raw.strip().lower() in _TRUTHY


def force_primary_enabled() -> bool:
    """总开关：True → 回到「一律 index 0」的旧行为（回滚兜底）。"""
    return _flag("FORCE_PRIMARY_IMAGE", default_on=False)


def l1_enabled() -> bool:
    return _flag("ARCHIVE_REF_L1")


def l2_enabled() -> bool:
    return _flag("ARCHIVE_REF_L2")


def deadline_ms() -> int:
    try:
        raw = int(os.getenv("ARCHIVE_REF_PICK_DEADLINE_MS", "").strip() or 10000)
    except ValueError:
        raw = 10000
    return max(500, min(raw, 60000))


def _extract_json_object(text: str) -> dict:
    """从模型输出里抠出第一个 JSON 对象（容忍 ```json 围栏/前后闲话）。"""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型输出里没有 JSON 对象")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型输出不是 JSON 对象")
    return data


def production_llm_fn(payload: dict) -> dict:
    """L1：元数据选图。抛错即层失败（picker 捕获降级）。"""
    from evoflow.models.openai_compat_invoke import invoke_chat_completion

    response = invoke_chat_completion(
        model=os.getenv("ARCHIVE_REF_L1_MODEL", "").strip() or None,
        messages=[{"role": "system", "content": _L1_SYSTEM}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        temperature=0.0,
        thinking_enabled=False,
    )
    text = str(((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    data = _extract_json_object(text)
    reason = str(data.get("reason") or "")
    indexes = data.get("indexes")
    if not isinstance(indexes, list):
        raise ValueError("L1 输出缺少 indexes")
    return {"indexes": indexes, "reason": reason}


def _vision_model_name() -> str:
    name = os.getenv("ARCHIVE_REF_VISION_MODEL", "").strip()
    if name:
        return name
    try:
        from evoflow.models.openai_compat_invoke import resolve_model_name

        resolved, _cfg = resolve_model_name(None)
        return str(resolved or "")
    except Exception:
        return ""


def _fetch_image_data_url(url: str) -> str:
    with httpx.Client(timeout=_L2_FETCH_TIMEOUT, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
    mime = str(response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if not mime.startswith("image/"):
        raise ValueError(f"档案图片返回了非图片内容：{mime}")
    raw = response.content
    if len(raw) > _L2_IMAGE_BYTES_MAX:
        raise ValueError("档案图片超过 L2 大小限制")
    return f"data:{mime};base64,{base64.standard_b64encode(raw).decode('ascii')}"


def _image_url(product_id: str, image_key: str) -> str:
    template = os.getenv("ARCHIVE_REF_IMAGE_URL_TEMPLATE", "").strip()
    if not template:
        raise RuntimeError("未配置 ARCHIVE_REF_IMAGE_URL_TEMPLATE，L2 不可用")
    if template.startswith("http://") and "://127.0.0.1" not in template and "://localhost" not in template:
        raise RuntimeError("ARCHIVE_REF_IMAGE_URL_TEMPLATE 必须是 https（本机调试除外）")
    if "{key}" not in template:
        raise RuntimeError("ARCHIVE_REF_IMAGE_URL_TEMPLATE 缺少 {key} 占位符")
    return template.format(key=quote(str(image_key), safe=""), product_id=quote(str(product_id), safe=""))


def _score_candidates(product_id: str, model: str, task_kind: str, candidates: list[dict]) -> dict[int, float]:
    """对未命中缓存的候选发一次 Vision 打分（一次多图调用）。"""
    from evoflow.models.openai_compat_invoke import invoke_chat_completion

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"这是商品档案的 {len(candidates)} 张候选参考图（依次对应下标 " + ", ".join(str(c["index"]) for c in candidates) + f"）。任务类型：{task_kind}。请按「主体完整、视角与任务匹配、清晰度、"
                '与要求相关性」综合打 0-10 分。只输出 JSON：{"scores": {"<下标>": <分数>}}，'
                "每张都要给分。"
            ),
        }
    ]
    for candidate in candidates:
        content.append({"type": "image_url", "image_url": {"url": _fetch_image_data_url(_image_url(product_id, str(candidate.get("image_key") or "")))}})
    response = invoke_chat_completion(
        model=os.getenv("ARCHIVE_REF_VISION_MODEL", "").strip() or None,
        messages=[{"role": "user", "content": content}],
        temperature=0.0,
        thinking_enabled=False,
    )
    text = str(((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    data = _extract_json_object(text)
    scores_raw = data.get("scores")
    if not isinstance(scores_raw, dict):
        raise ValueError("L2 输出缺少 scores")
    out: dict[int, float] = {}
    for key, value in scores_raw.items():
        try:
            out[int(key)] = float(value)
        except (TypeError, ValueError):
            continue
    if not out:
        raise ValueError("L2 scores 为空")
    return out


def cached_vision_fn(product_id: str, task_kind: str):
    """构造带缓存的 L2 vision_fn 闭包（键：asset_id+key+model+task_kind）。

    ``vision_fn(candidates) -> {index: score}``；candidates 项需带
    ``image_key``（由网关从档案行的 ``image_keys`` 注入）。任一候选取图/
    打分失败 → 整层抛错 → picker 降级。全命中缓存时不发起调用（不计费）。
    """
    model = _vision_model_name()

    def vision_fn(candidates) -> dict[int, float]:
        scored: dict[int, float] = {}
        misses: list[dict] = []
        for candidate in candidates:
            image_key = str((candidate or {}).get("image_key") or "")
            cache_key = (product_id, image_key, model, task_kind)
            if image_key and cache_key in _L2_SCORE_CACHE:
                scored[int(candidate["index"])] = _L2_SCORE_CACHE[cache_key]
            else:
                misses.append(dict(candidate))
        if misses:
            fresh = _score_candidates(product_id, model, task_kind, misses)
            for candidate in misses:
                index = int(candidate["index"])
                if index in fresh:
                    image_key = str(candidate.get("image_key") or "")
                    if image_key:
                        if len(_L2_SCORE_CACHE) >= _L2_CACHE_MAX:
                            _L2_SCORE_CACHE.clear()
                        _L2_SCORE_CACHE[(product_id, image_key, model, task_kind)] = fresh[index]
                    scored[index] = fresh[index]
        if not scored:
            raise ValueError("L2 无任何有效打分")
        return scored

    return vision_fn
