"""档案参考图自动优选（纯函数，L0 → L1 → L2，可降级可回滚）。

层次约定（与 1.4.11 派活 steps 钉死口径一致）：

- **L0 规则层**：任务 ↔ 视角偏好表打分；唯一最优即出结果（不调模型）。
- **L1 元数据层**：把压缩后的图片元数据（index/view_angle/is_primary）交给
  LLM 选下标；**不传原图像素**。
- **L2 Vision 层**：对 L0 粗排后的候选（≤6 张）做视觉打分；生产接线在
  网关侧（``app.gateway.routers.archive_ref_pick``），这里只定义可注入的
  ``vision_fn`` 契约。
- 任一层抛错/超预算（deadline 用尽）→ 降下一层；最终仍失败且档案有图 →
  ``[0] + layer="forced0"``（拍板 C）；无图 → 抛 :class:`NoImagesError`。
- ``force_primary=True``（对应 ``FORCE_PRIMARY_IMAGE=1`` 总开关）→ 有图即
  ``[0] + forced0``，不调任何模型。
- ``explicit_indexes`` 校验合法后直接 ``manual``，**不**跑自动；非法下标抛
  :class:`ValueError`（调用方 400，不静默改 0）。

视角枚举说明：``view_angle`` 实际字符串由外部工作台服务（写入侧）决定，
本仓 ``products_list`` 读取时空串映射 ``other``、缺失映射 ``unmarked``。
本模块按逻辑桶（white/front/detail/scene/full）做关键词归一化匹配；
未识别 / ``unmarked`` / ``other`` 一律当无标注处理。视频多图的「异视角」
去重按归一化后的原始标注串判断（不同串即视为不同视角）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# 任务类型（video_multi = 视频多图，want_count 2..3）
TASK_KINDS = ("image_main", "image_detail", "video_cover", "video_multi")

# 逻辑桶 → 现网字符串关键词（大小写不敏感、子串匹配；命中即归桶）
_ANGLE_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("white", ("white", "白底", "纯白", "白背", "packshot", "棚拍")),
    ("front", ("front", "正面", "前脸", "frontal")),
    ("detail", ("detail", "细节", "局部", "材质", "material", "texture", "closeup", "close-up", "close up", "特写")),
    ("scene", ("scene", "场景", "生活", "lifestyle", "情境", "实景", "外景")),
    ("full", ("full", "全身", "整身", "整体", "全貌", "fullbody", "full body")),
)

# 任务 → (优先桶, 次选桶, 是否计 is_primary 次选分)。
# 只有 image_main 表格把 is_primary 列为次选；detail/cover 的次选是视角桶。
_TASK_RULES: dict[str, tuple[tuple[str, ...], tuple[str, ...], bool]] = {
    "image_main": (("white", "front"), (), True),
    "image_detail": (("detail",), ("front",), False),
    "video_cover": (("scene", "full"), ("front",), False),
}

# L2 候选上限（L0 粗排后截断）
MAX_L2_CANDIDATES = 6
# L0 置信门槛：至少命中次选视角桶（≥50）才算高置信；仅 is_primary(10) 不算，
# 仍按「全 unmarked」升级 L1/L2，失败回落 forced0（T4 语义）。
_L0_CONFIDENT_MIN = 50
_REASON_MAX = 200


class NoImagesError(ValueError):
    """档案没有任何参考图；调用方应 400/404，禁止空提交扣费。"""


@dataclass
class PickResult:
    indexes: list[int]
    layer: str  # "L0" | "L1" | "L2" | "manual" | "forced0"
    reason: str
    candidates_considered: int = 0


@dataclass
class _Image:
    index: int
    raw_angle: str  # 归一化（lower/strip）后的原始标注串
    bucket: str  # 逻辑桶；未识别 → "unmarked"
    is_primary: bool
    score: int = 0  # L0 分：primary=100 / secondary=50 / is_primary=10 / 无信号=0


def _bucket_of(angle: str) -> str:
    text = str(angle or "").strip().lower()
    if not text or text in {"unmarked", "other", "unknown", "none"}:
        return "unmarked"
    for bucket, keywords in _ANGLE_BUCKETS:
        if any(k in text for k in keywords):
            return bucket
    return "unmarked"


def _norm_meta(images_meta: list[dict]) -> list[_Image]:
    out: list[_Image] = []
    for i, row in enumerate(images_meta or []):
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("index", i))
        except (TypeError, ValueError):
            index = i
        raw = str(row.get("view_angle") or "").strip()
        out.append(_Image(index=index, raw_angle=raw.lower(), bucket=_bucket_of(raw), is_primary=bool(row.get("is_primary"))))
    return out


def _score_all(images: list[_Image], primary: tuple[str, ...], secondary: tuple[str, ...], *, use_primary: bool) -> None:
    for img in images:
        if img.bucket in primary:
            img.score = 100
        elif img.bucket in secondary:
            img.score = 50
        elif use_primary and img.is_primary:
            img.score = 10
        else:
            img.score = 0


def _unique_max(images: list[_Image]) -> _Image | None:
    """唯一最高分且达到置信门槛 → 该图；平局/信号不足 → None（升级 L1/L2）。"""
    best: _Image | None = None
    tied = False
    for img in images:
        if best is None or img.score > best.score:
            best, tied = img, False
        elif img.score == best.score:
            tied = True
    if best is None or best.score < _L0_CONFIDENT_MIN or tied:
        return None
    return best


def _reason_for(img: _Image, task_kind: str) -> str:
    labels = {"image_main": "主图任务优先白底/正面", "image_detail": "细节任务优先细节/材质", "video_cover": "封面优先场景/全身"}
    label = labels.get(task_kind, "按任务视角偏好")
    angle = img.raw_angle or "unmarked"
    return f"{label}，档案 #{img.index} view_angle={angle}"[:_REASON_MAX]


def _check_explicit(explicit: list[int], images: list[_Image], *, single: bool) -> list[int]:
    """校验显式下标（保持调用顺序、去重）；非法抛 ValueError → 调用方 400。"""
    valid = {img.index for img in images}
    picked: list[int] = []
    for raw in explicit:
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise ValueError("参考图下标必须是整数")
        if raw < 0 or raw not in valid:
            raise ValueError(f"参考图下标无效：{raw}")
        if raw in picked:
            raise ValueError(f"参考图下标重复：{raw}")
        picked.append(raw)
    if single and len(picked) != 1:
        raise ValueError("主图任务必须只选择 1 张参考图（恰好 1 个下标）")
    if not single and not 1 <= len(picked) <= 3:
        raise ValueError("参考图必须选择 1-3 张")
    return picked


def _run_llm(llm_fn, payload: dict, *, deadline: float, want_count: int, images: list[_Image], single: bool) -> PickResult | None:
    """L1：元数据选图；抛错/输出非法/超预算（含返回时已超）→ None（降级）。"""
    if llm_fn is None or (deadline - time.monotonic()) <= 0:
        return None
    try:
        raw = llm_fn(payload)
        if time.monotonic() > deadline:
            return None
        picked = raw.get("indexes") if isinstance(raw, dict) else None
        reason = str(raw.get("reason") or "") if isinstance(raw, dict) else ""
        if not isinstance(picked, list):
            return None
        result = _check_explicit(picked, images, single=single)
        if single and len(result) != 1:
            return None
        if not single and not 1 <= len(result) <= want_count:
            return None
        return PickResult(indexes=result, layer="L1", reason=(reason or "L1 元数据选图")[:_REASON_MAX], candidates_considered=len(images))
    except Exception:
        return None


def _run_vision(vision_fn, candidates: list[_Image], *, deadline: float, want_count: int, images: list[_Image], single: bool) -> PickResult | None:
    """L2：视觉打分选图；抛错/非法输出/超预算（含返回时已超）→ None（降级）。"""
    if vision_fn is None or not candidates or (deadline - time.monotonic()) <= 0:
        return None
    try:
        scores = vision_fn(candidates)
        if time.monotonic() > deadline or not isinstance(scores, dict):
            return None
        valid = {img.index: float(scores[img.index]) for img in candidates if isinstance(scores.get(img.index), (int, float))}
        if not valid:
            return None
        ordered = sorted(valid.items(), key=lambda kv: (-kv[1], kv[0]))
        angle_of = {img.index: img.raw_angle for img in images}
        if single:
            best_index = ordered[0][0]
            return PickResult(indexes=[best_index], layer="L2", reason=f"Vision 打分最高 #{best_index}（{ordered[0][1]:.1f} 分）", candidates_considered=len(candidates))
        # 视频多图：top1 做封面，其后排除同 view_angle，不足再允许同视角高分
        chosen: list[int] = [ordered[0][0]]
        used_angles = {angle_of.get(chosen[0], "")}
        for allow_same_angle in (False, True):
            for index, _score in ordered:
                if len(chosen) >= want_count:
                    break
                if index in chosen:
                    continue
                if not allow_same_angle and angle_of.get(index, "") in used_angles:
                    continue
                chosen.append(index)
                used_angles.add(angle_of.get(index, ""))
        return PickResult(indexes=chosen, layer="L2", reason=f"Vision 打分选封面 #{chosen[0]}，其余按分数与异视角补齐 {chosen}", candidates_considered=len(candidates))
    except Exception:
        return None


def _fill_multi(cover: _Image, images: list[_Image], want_count: int) -> list[int]:
    """L0 多图补齐：cover 之后优先异视角（同分按档案次序）。"""
    chosen = [cover.index]
    used = {cover.raw_angle}
    rest = sorted((i for i in images if i.index != cover.index), key=lambda i: (-i.score, i.index))
    for allow_same_angle in (False, True):
        for img in rest:
            if len(chosen) >= want_count:
                return chosen
            if img.index in chosen:
                continue
            if not allow_same_angle and img.raw_angle in used:
                continue
            chosen.append(img.index)
            used.add(img.raw_angle)
    return chosen


def _meta_payload(task_kind: str, want_count: int, prompt: str, images: list[_Image]) -> dict:
    """L1 输入：压缩元数据 + 任务 + 截断 prompt；不含任何图像像素。"""
    return {"task_kind": task_kind, "want_count": want_count, "prompt": str(prompt or "")[:500], "images": [{"index": i.index, "view_angle": i.raw_angle, "is_primary": i.is_primary} for i in images]}


def resolve_reference_indexes(
    *,
    task_kind: str,
    images_meta: list[dict],
    explicit_indexes: list[int] | None = None,
    want_count: int = 1,
    prompt: str = "",
    force_primary: bool = False,
    enable_l1: bool = True,
    enable_l2: bool = True,
    vision_fn=None,
    llm_fn=None,
    deadline_ms: int = 10000,
) -> PickResult:
    """按 L0→L1→L2 为做图/视频任务选档案参考图下标。

    优先级（写死，勿改）：
    1. ``force_primary`` → ``[0] + forced0``（档案有图；无图抛 NoImagesError）
    2. ``explicit_indexes`` 非空 → 校验合法后 ``manual``（不跑自动）
    3. L0 唯一最优 → ``L0``；平局/全 unmarked → L1 → L2（均可在链上降级）
    4. 全部失败且有图 → ``[0] + forced0``；无图 → NoImagesError

    ``llm_fn(payload) -> {"indexes": [...], "reason": str}``；
    ``vision_fn(candidates) -> {index: score}``；两者均可注入 mock，
    抛错即视为该层失败（降级），不向上冒泡。
    """
    if task_kind not in TASK_KINDS:
        raise ValueError(f"未知任务类型：{task_kind}")
    images = _norm_meta(images_meta)
    total = len(images)
    if total == 0:
        raise NoImagesError("商品档案没有参考图，请先在工作台补图")
    want_count = max(1, min(int(want_count or 1), 3))
    if task_kind == "video_cover" and want_count > 1:
        task_kind = "video_multi"
    if task_kind == "video_multi" and want_count == 1:
        task_kind = "video_cover"
    single = task_kind != "video_multi"

    # 1) 总开关：回到「一律 index 0」的今日行为（回滚兜底）
    if force_primary:
        return PickResult([0], "forced0", "FORCE_PRIMARY_IMAGE 兜底启用，回退档案主图 #0", total)

    # 2) 用户显式指定 → manual（优先于任何自动；非法下标抛错，不静默改 0）
    if explicit_indexes:
        picked = _check_explicit(list(explicit_indexes), images, single=single)
        if single and len(picked) != 1:
            raise ValueError("主图任务必须只选择 1 张参考图（恰好 1 个下标）")
        if not single and not 1 <= len(picked) <= want_count:
            raise ValueError(f"参考图数量须为 1-{want_count} 张")
        return PickResult(picked, "manual", "用户显式指定档案参考图", total)

    # 快捷路径：档案只有 1 张（或不足 want_count 张）→ 直接全用，无需模型
    if total == 1:
        return PickResult([images[0].index], "L0", "档案仅 1 张参考图", total)
    if not single and total <= want_count:
        return PickResult([i.index for i in sorted(images, key=lambda x: x.index)], "L0", f"档案仅 {total} 张参考图，全部选用", total)

    primary, secondary, use_primary = _TASK_RULES["video_cover" if task_kind == "video_multi" else task_kind]
    _score_all(images, primary, secondary, use_primary=use_primary)
    deadline = time.monotonic() + max(0, int(deadline_ms)) / 1000.0
    forced = PickResult([0], "forced0", "自动优选不可用，回退档案主图 #0", total)

    if single:
        best = _unique_max(images)
        if best is not None:
            return PickResult([best.index], "L0", _reason_for(best, task_kind), total)

        # 置信不足（平局/全 unmarked）→ L1 → L2 → forced0
        if enable_l1:
            l1 = _run_llm(llm_fn, _meta_payload(task_kind, 1, prompt, images), deadline=deadline, want_count=1, images=images, single=True)
            if l1 is not None:
                return l1
        elif not enable_l2:
            # L1/L2 全关时的唯一例外（A.1）：达到置信门槛的同分平局可取靠前下标；
            # 信号不足（全 unmarked / 仅主图标记）仍走 forced0，不冒充 L0 置信。
            top = max(i.score for i in images)
            if top >= _L0_CONFIDENT_MIN and sum(1 for i in images if i.score == top) > 1:
                tied = min((i for i in images if i.score == top), key=lambda i: i.index)
                return PickResult([tied.index], "L0", f"多张同分且自动层已关闭，取靠前 #{tied.index}", total)
            return forced
        if enable_l2 and (deadline - time.monotonic()) > 0:
            candidates = sorted(images, key=lambda i: (-i.score, i.index))[:MAX_L2_CANDIDATES]
            l2 = _run_vision(vision_fn, candidates, deadline=deadline, want_count=1, images=images, single=True)
            if l2 is not None:
                return l2
        return forced

    # ── 视频多图（video_multi）：拍板 D 异视角优先 ──────────────────
    # 封面平局（同桶多张）不影响多样性目标 → 取靠前，不升级模型层；
    # 仅当完全无视角信号（全 unmarked）才升级 L1/L2，失败 → forced0。
    top = max(i.score for i in images)
    if top > 0:
        cover = min((i for i in images if i.score == top), key=lambda i: i.index)
        indexes = _fill_multi(cover, images, want_count)
        return PickResult(indexes, "L0", f"封面取 #{cover.index}（{cover.raw_angle or 'unmarked'}），其余按异视角补齐 {indexes}", total)
    # 封面置信不足 → L1（多图）→ L2；仍失败 → forced0（不静默改选非 0）
    if enable_l1:
        l1 = _run_llm(llm_fn, _meta_payload("video_multi", want_count, prompt, images), deadline=deadline, want_count=want_count, images=images, single=False)
        if l1 is not None:
            return l1
    if enable_l2 and (deadline - time.monotonic()) > 0:
        candidates = sorted(images, key=lambda i: (-i.score, i.index))[:MAX_L2_CANDIDATES]
        l2 = _run_vision(vision_fn, candidates, deadline=deadline, want_count=want_count, images=images, single=False)
        if l2 is not None:
            return l2
    return forced
