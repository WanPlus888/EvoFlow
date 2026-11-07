"""Fixed, authenticated tools for the local AI commerce workbench."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Literal
from urllib.parse import urlsplit

from langchain.tools import tool
from pydantic import BaseModel, Field

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_PRODUCT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

# 全部工作台**生产**工具名（岗位白名单单一事实源 / L2）。
# 这些工具不随模式目录/继承默认发放：必须由岗位显式勾选
# （AgentConfig.tools / worker_profile.tools）后才可解析绑定；
# 未授权角色在会话绑定与 worker 继承两条路径上都会被剥离（fail-closed）。
# 与 L1 ``platform_scope``（平台域 ACL）分层：platform「不设限」不会放开本集合。
# ``draft_workbench_order`` 故意不在此集合（草稿非生产，三岗可显式挂在 BASE_TOOLS）。
WORKBENCH_TOOL_NAMES: frozenset[str] = frozenset({
    "workbench_products_list",
    "workbench_image_submit",
    "workbench_image_status",
    "workbench_video_options",
    "workbench_video_submit",
    "workbench_video_status",
})


def _worker_request(path: str, *, method: str = "GET", payload: dict | None = None,
                    external_ref: str = "") -> dict:
    base = (os.getenv("EVOFLOW_GATEWAY_URL") or "http://127.0.0.1:8012").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return {"ok": False, "error": "工作台工具仅允许访问本机 Gateway"}
    token = (os.getenv("EVOFLOW_WORKBENCH_TOOL_TOKEN") or "").strip()
    if not token:
        return {"ok": False, "error": "工作台工具未配置访问凭据"}
    if not path.startswith("/api/opsboard/worker/"):
        return {"ok": False, "error": "工作台工具只允许固定操作"}
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "X-EvoFlow-Worker-Key": token}
    if external_ref:
        headers["X-EvoFlow-External-Ref"] = external_ref
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
        return data if isinstance(data, dict) else {"ok": False, "error": "工作台返回格式无效"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"工作台请求失败（HTTP {exc.code}）"}
    except Exception as exc:
        return {"ok": False, "error": f"工作台暂不可用（{type(exc).__name__}）"}


class ProductListInput(BaseModel):
    search: str = Field("", max_length=60, description="按商品名称筛选，可留空查看最近档案")


class ImageSubmitInput(BaseModel):
    external_ref: str = Field(..., max_length=80, description="工单溯源号，同一工单重试必须原样传入")
    product_id: str = Field(..., max_length=80, description="工作台商品档案 ID")
    prompt: str = Field(..., min_length=8, max_length=3000, description="已确认的单图生成要求")
    ratio: Literal["1:1", "3:4", "4:3", "9:16", "auto"] = "3:4"


class ImageStatusInput(BaseModel):
    record_id: str = Field(..., max_length=100, description="单图提交返回的工作台记录 ID")
    external_ref: str = Field(..., max_length=80, description="原工单溯源号，用于验证预览归属")


class VideoOptionsInput(BaseModel):
    search: str = Field("", max_length=60, description="可选供应商名称筛选")


class VideoSubmitInput(BaseModel):
    external_ref: str = Field(..., max_length=80, description="工单溯源号，用于任务幂等")
    product_id: str = Field(..., max_length=80, description="工作台商品档案 ID")
    provider: str = Field(..., min_length=1, max_length=80, description="从 workbench_video_options 返回的供应商名")
    model: str = Field(..., min_length=1, max_length=120, description="该供应商当前允许的模型 ID")
    image_indexes: list[int] = Field(default_factory=lambda: [0], description="档案图片下标，最多 3 张")
    prompt: str = Field(..., min_length=8, max_length=3000, description="视频画面与运动要求")
    narration: str = Field("", max_length=2000, description="配音文案")
    ratio: str = Field("9:16", max_length=8, description="必须使用所选模型支持的比例")
    resolution: str = Field("720p", max_length=12, description="必须使用所选模型支持的分辨率")
    duration: int = Field(8, ge=1, le=180, description="必须使用所选模型支持的时长")


class VideoStatusInput(BaseModel):
    job_id: str = Field(..., max_length=100, description="短视频提交返回的工作台任务 ID")


@tool("workbench_products_list", args_schema=ProductListInput)
def workbench_products_list(search: str = "") -> str:
    """只读查询工作台商品档案和可用参考图片，生产前必须先确认商品。"""
    query = urllib.parse.urlencode({"search": search.strip()[:60]})
    return json.dumps(_worker_request("/api/opsboard/worker/products?" + query), ensure_ascii=False)


@tool("workbench_image_submit", args_schema=ImageSubmitInput)
def workbench_image_submit(external_ref: str, product_id: str, prompt: str,
                           ratio: str = "3:4") -> str:
    """通过工作台提交商品主图；同一工单重放返回现有记录，不会重复生成。"""
    ref, product = external_ref.strip(), product_id.strip()
    if not _REF_RE.fullmatch(ref) or not _PRODUCT_ID_RE.fullmatch(product):
        return json.dumps({"ok": False, "error": "工单号或商品档案 ID 格式无效"}, ensure_ascii=False)
    if ratio not in {"1:1", "3:4", "4:3", "9:16", "auto"}:
        return json.dumps({"ok": False, "error": "图片比例无效"}, ensure_ascii=False)
    result = _worker_request("/api/opsboard/worker/images", method="POST", payload={
        "external_ref": ref, "product_id": product,
        "prompt": prompt.strip(), "ratio": ratio,
    })
    return json.dumps(result, ensure_ascii=False)


@tool("workbench_image_status", args_schema=ImageStatusInput)
def workbench_image_status(record_id: str, external_ref: str) -> str:
    """查询工作台单图状态和预览引用；必须传回原工单溯源号。"""
    rid, ref = record_id.strip(), external_ref.strip()
    if not _ID_RE.fullmatch(rid) or not _REF_RE.fullmatch(ref):
        return json.dumps({"ok": False, "error": "记录 ID 或工单溯源号格式无效"}, ensure_ascii=False)
    result = _worker_request(f"/api/opsboard/worker/images/{rid}", external_ref=ref)
    if not result.get("ok"):
        return json.dumps(result, ensure_ascii=False)
    if result.get("external_ref") != ref:
        return json.dumps({"ok": False, "error": "工作台记录与原工单号不匹配"}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


@tool("workbench_video_options", args_schema=VideoOptionsInput)
def workbench_video_options(search: str = "") -> str:
    """只读查询工作台当前允许的短视频供应商、模型和能力。"""
    query = urllib.parse.urlencode({"search": search.strip()[:60]})
    return json.dumps(_worker_request("/api/opsboard/worker/video-options?" + query), ensure_ascii=False)


@tool("workbench_video_submit", args_schema=VideoSubmitInput)
def workbench_video_submit(external_ref: str, product_id: str, prompt: str,
                           provider: str, model: str, narration: str = "",
                           image_indexes: list[int] | None = None, ratio: str = "9:16",
                           resolution: str = "720p", duration: int = 8) -> str:
    """通过工作台提交短视频任务，使用工单号构造稳定提交键防止重复扣费。"""
    ref, product = external_ref.strip(), product_id.strip()
    indexes = image_indexes or [0]
    if not _REF_RE.fullmatch(ref) or not _PRODUCT_ID_RE.fullmatch(product):
        return json.dumps({"ok": False, "error": "工单号或商品档案 ID 格式无效"}, ensure_ascii=False)
    if len(indexes) > 3 or any(not isinstance(i, int) or i < 0 for i in indexes):
        return json.dumps({"ok": False, "error": "最多选择 3 张有效的档案图片"}, ensure_ascii=False)
    result = _worker_request("/api/opsboard/worker/videos", method="POST", payload={
        "external_ref": ref, "product_id": product, "image_indexes": indexes,
        "prompt": prompt.strip(), "narration": narration.strip(),
        "provider": provider.strip(), "model": model.strip(),
        "ratio": ratio, "resolution": resolution, "duration": duration,
    })
    return json.dumps(result, ensure_ascii=False)


@tool("workbench_video_status", args_schema=VideoStatusInput)
def workbench_video_status(job_id: str) -> str:
    """查询工作台短视频任务状态、阶段、失败原因和成品键。"""
    jid = job_id.strip()
    if not _ID_RE.fullmatch(jid):
        return json.dumps({"ok": False, "error": "视频任务 ID 格式无效"}, ensure_ascii=False)
    return json.dumps(_worker_request(f"/api/opsboard/worker/videos/{jid}"), ensure_ascii=False)
