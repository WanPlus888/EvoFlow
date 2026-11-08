"""Narrow employee operations proxied to the authenticated workbench service account."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import os
import re
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from app.gateway.routers import archive_ref_pick, ops_summary
from evoflow.authz.http_guard import require_org_admin
from evoflow.collab.archive_ref_picker import PickResult, resolve_reference_indexes

logger = logging.getLogger("evoflow.gateway.worker_workbench")

router = APIRouter(prefix="/api/opsboard/worker", tags=["opsboard-worker"])
preview_router = APIRouter(prefix="/api/opsboard", tags=["opsboard-preview"])
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_IMAGE_RATIOS = {"1:1", "3:4", "4:3", "9:16", "auto"}
_VIDEO_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9"}
_ref_locks: dict[str, asyncio.Lock] = {}
_PREVIEW_BYTES_MAX = 50 * 1024 * 1024
_IMAGE_REF_RE = re.compile(r"^workbench-image://([A-Za-z0-9_-]{1,100})/(0|[1-9][0-9]{0,2})/([A-Za-z0-9][A-Za-z0-9._-]{0,79})$")


def _guard(key: str) -> None:
    expected = os.getenv("EVOFLOW_WORKBENCH_TOOL_TOKEN", "").strip()
    if not expected or not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=403, detail="worker tool access denied")
    try:
        ops_summary._require_workbench_admin()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="工作台管理员代理不可用") from exc


def _ref(value: Any) -> str:
    result = str(value or "").strip()
    if not _REF_RE.fullmatch(result):
        raise HTTPException(status_code=400, detail="工单溯源号格式无效")
    return result


def _is_issued_preview_ref(record_id: str, item_index: int, external_ref: str) -> bool:
    if not _ID_RE.fullmatch(record_id) or item_index < 0 or item_index > 100 or not _REF_RE.fullmatch(external_ref):
        return False
    try:
        from evoflow.admin.tasks import list_tasks

        rows = list_tasks(limit=500, include_subtasks=True).get("tasks", [])
    except Exception:
        return False
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("assigned_to") or "").strip():
            continue
        searchable = "\\n".join(str(row.get(key) or "") for key in ("name", "description", "summary", "result"))
        if external_ref in searchable:
            return True
    return False


def _safe_record(record: dict, *, deduped: bool = False) -> dict[str, Any]:
    rid = str(record.get("id") or "")
    external_ref = str(record.get("external_ref") or "")
    return {"ok": True, "id": rid,
            "title": str(record.get("title") or "")[:120],
            "status": str(record.get("status") or ""),
            "running": bool(record.get("running")),
            "external_ref": external_ref,
            "error": str(record.get("error") or "")[:300], "deduped": deduped,
            "items": [{"id": str(item.get("id") or ""),
                       "status": str(item.get("status") or ""),
                       "preview_ref": (f"workbench-image://{rid}/{i}/{external_ref}"
                                       if external_ref and item.get("status") == "done" and item.get("file") else ""),
                       "error": str(item.get("error") or item.get("err") or "")[:300]}
                      for i, item in enumerate((record.get("items") or [])[:20]) if isinstance(item, dict)]}


def _safe_preview_redirect(response) -> None:
    base, _, _ = ops_summary._conf()
    trusted = urlsplit(base)
    for previous in [*response.history, response]:
        url = urlsplit(str(previous.url))
        if not url.hostname or url.username or url.password:
            raise HTTPException(status_code=502, detail="预览重定向目标无效")
        host = url.hostname.lower().rstrip(".")
        same_workbench = (url.scheme == trusted.scheme and host == (trusted.hostname or "").lower()
                          and url.port == trusted.port and url.path.startswith("/api/auth/worker-preview/"))
        if same_workbench:
            continue
        if url.scheme != "https":
            raise HTTPException(status_code=502, detail="预览重定向必须使用 HTTPS")
        try:
            address = ipaddress.ip_address(url.hostname.strip("[]"))
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise HTTPException(status_code=502, detail="预览重定向目标不允许访问")
        if not host.endswith(".myqcloud.com"):
            raise HTTPException(status_code=502, detail="预览重定向目标不在允许范围")


def _fetch_preview_response(client: httpx.Client, url: str, headers: dict[str, str]) -> tuple[bytes, str, str | None]:
    with client.stream("GET", url, headers=headers) as response:
        if response.status_code in {301, 302, 303, 307, 308}:
            return b"", "", str(response.headers.get("Location") or "")
        if 300 <= response.status_code < 400:
            raise HTTPException(status_code=502, detail="图片预览存在多级重定向，已拒绝")
        response.raise_for_status()
        _safe_preview_redirect(response)
        mime = str(response.headers.get("Content-Type") or "")
        if not mime.lower().startswith("image/"):
            raise HTTPException(status_code=502, detail="工作台预览返回了非图片内容")
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > _PREVIEW_BYTES_MAX:
            raise HTTPException(status_code=413, detail="图片超过预览大小限制")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > _PREVIEW_BYTES_MAX:
                raise HTTPException(status_code=413, detail="图片超过预览大小限制")
            chunks.append(chunk)
        return b"".join(chunks), mime, None


def _fetch_workbench_preview(record_id: str, item_index: int, *, expected_ref: str = "",
                              preview_ref: str = "") -> tuple[bytes, str]:
    ticket = ops_summary._authed_post("/api/opsboard/worker/preview-ticket", {
        "record_id": record_id, "item_index": item_index})
    stored_ref = str(ticket.get("external_ref") or "")
    if expected_ref and not hmac.compare_digest(expected_ref, stored_ref):
        raise HTTPException(status_code=404, detail="图片预览引用不匹配")
    if preview_ref:
        ref_match = _IMAGE_REF_RE.fullmatch(preview_ref)
        if (not ref_match or ref_match.group(1) != record_id or int(ref_match.group(2)) != item_index
                or not hmac.compare_digest(ref_match.group(3), stored_ref)
                or not _is_issued_preview_ref(record_id, item_index, stored_ref)):
            raise HTTPException(status_code=404, detail="图片预览引用不匹配")
    base, _, _ = ops_summary._conf()
    url = base + str(ticket.get("preview_path") or "")
    headers = {**ops_summary._workbench_auth_headers(),
               "X-Workbench-Preview-Key": os.getenv("EVOFLOW_WORKBENCH_PREVIEW_KEY", "").strip(),
               "X-Workbench-Preview-Expires": str(ticket.get("expires") or ""),
               "X-Workbench-Preview-Ref": stored_ref,
               "X-Workbench-Preview-Ticket": str(ticket.get("signature") or "")}
    with httpx.Client(timeout=25, follow_redirects=False) as client:
        raw, mime, location = _fetch_preview_response(client, url, headers)
        if location:
            redirected = urlsplit(location)
            host = (redirected.hostname or "").lower().rstrip(".")
            try:
                address = ipaddress.ip_address(host.strip("[]"))
            except ValueError:
                address = None
            if (redirected.scheme != "https" or not host.endswith(".myqcloud.com")
                    or (address is not None and not address.is_global)
                    or redirected.username or redirected.password):
                raise HTTPException(status_code=502, detail="图片对象存储重定向地址无效")
            raw, mime, second_location = _fetch_preview_response(
                client, location, {"Accept": "image/*"})
            if second_location:
                raise HTTPException(status_code=502, detail="图片预览存在多级重定向，已拒绝")
    return raw, mime


def _preview_response(record_id: str, item_index: int, *, expected_ref: str = "",
                      preview_ref: str = "") -> Response:
    raw, mime = _fetch_workbench_preview(record_id, item_index, expected_ref=expected_ref,
                                         preview_ref=preview_ref)
    return Response(content=raw, media_type=mime, headers={
        "Cache-Control": "private, no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    })


@router.get("/images/{record_id}/preview/{item_index}")
async def image_preview_bytes(record_id: str, item_index: int,
                              x_evoflow_worker_key: str = Header(default=""),
                              x_evoflow_image_ref: str = Header(default=""),
                              x_evoflow_external_ref: str = Header(default="")) -> Response:
    _guard(x_evoflow_worker_key)
    expected = f"workbench-image://{record_id}/{item_index}/{x_evoflow_external_ref}"
    if not x_evoflow_external_ref or x_evoflow_image_ref != expected:
        raise HTTPException(status_code=404, detail="Workbench image reference mismatch")
    try:
        return _preview_response(record_id, item_index, expected_ref=x_evoflow_external_ref,
                                 preview_ref=expected)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code,
                            detail="工作台图片预览不可用") from exc


@preview_router.get("/image-preview/{record_id}/{item_index}")
async def browser_image_preview(record_id: str, item_index: int,
                                request: Request,
                                external_ref: str = Header(default="", alias="X-EvoFlow-External-Ref")) -> Response:
    require_org_admin(request)
    if not _ID_RE.fullmatch(record_id) or item_index < 0 or item_index > 100:
        raise HTTPException(status_code=404, detail="图片记录不存在")
    ticket = ops_summary._authed_post("/api/opsboard/worker/preview-ticket", {
        "record_id": record_id, "item_index": item_index})
    issued_ref = str(ticket.get("external_ref") or "")
    if not _REF_RE.fullmatch(issued_ref):
        raise HTTPException(status_code=404, detail="图片记录不存在")
    if external_ref and (not hmac.compare_digest(issued_ref, external_ref)
                         or not _is_issued_preview_ref(record_id, item_index, issued_ref)):
        raise HTTPException(status_code=404, detail="图片记录不存在")
    try:
        preview_ref = (f"workbench-image://{record_id}/{item_index}/{issued_ref}"
                       if external_ref else "")
        return _preview_response(record_id, item_index, expected_ref=issued_ref,
                                 preview_ref=preview_ref)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code,
                            detail="工作台图片预览不可用") from exc


def _safe_video(job: dict) -> dict[str, Any]:
    return {"ok": True, "id": str(job.get("id") or job.get("job_id") or ""),
            "title": str(job.get("title") or "")[:120],
            "status": str(job.get("status") or ""),
            "stage": str(job.get("stage") or "")[:120],
            "error": str(job.get("error") or "")[:300],
            "result_key": str(job.get("result_key") or "")}


def _asset_row(product_id: Any) -> dict:
    """按 ID 取档案行（404 若不存在；502 若工作台不可达）。"""
    pid = str(product_id or "").strip()
    if not _ID_RE.fullmatch(pid):
        raise HTTPException(status_code=400, detail="商品档案 ID 格式无效")
    try:
        data = ops_summary._authed_get("/api/product-assets")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="工作台商品档案暂不可用") from exc
    asset = next((row for row in data.get("assets", [])
                  if isinstance(row, dict) and str(row.get("id") or "") == pid), None)
    if not asset:
        raise HTTPException(status_code=404, detail="商品档案不存在")
    return asset


def _angle_at(asset: dict, index: int) -> str:
    """与 products_list 同口径：空标注→other；缺失→unmarked。"""
    angles = asset.get("view_angles") or []
    return str(angles[index] or "other") if index < len(angles) else "unmarked"


def _images_meta(asset: dict) -> list[dict]:
    keys = asset.get("image_keys") or []
    return [{"index": i, "view_angle": _angle_at(asset, i), "is_primary": i == 0,
             "image_key": str(keys[i] or "")}
            for i, _ in enumerate(keys[:60])]


def _asset(product_id: Any, indexes: Any, asset_row: dict | None = None) -> tuple[dict, list[str]]:
    pid = str(product_id or "").strip()
    if not _ID_RE.fullmatch(pid):
        raise HTTPException(status_code=400, detail="商品档案 ID 格式无效")
    if not isinstance(indexes, list) or not indexes or len(indexes) > 3:
        raise HTTPException(status_code=400, detail="请选择 1-3 张档案参考图")
    if asset_row is None:
        asset_row = _asset_row(pid)
    images = asset_row.get("image_keys") or []
    keys: list[str] = []
    for index in indexes:
        if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= len(images):
            raise HTTPException(status_code=400, detail="参考图下标无效")
        key = str(images[index] or "")
        if not key or key in keys:
            raise HTTPException(status_code=400, detail="参考图下标重复或图片不可用")
        keys.append(key)
    return asset_row, keys


def _resolve_auto_pick(product_id: str, asset_row: dict, *, task_kind: str,
                       want_count: int, prompt: str) -> PickResult:
    """自动优选（L0→L1→L2，含总开关/分层开关/预算），同步供 to_thread 调用。

    档案无图 → 400「请先补图」（禁止空提交扣费）；开关与 L1/L2 生产函数
    见 :mod:`app.gateway.routers.archive_ref_pick`。
    """
    if not (asset_row.get("image_keys") or []):
        raise HTTPException(status_code=400,
                            detail="商品档案没有参考图，请先在工作台商品档案补图")
    try:
        result = resolve_reference_indexes(
            task_kind=task_kind, images_meta=_images_meta(asset_row),
            want_count=want_count, prompt=prompt,
            force_primary=archive_ref_pick.force_primary_enabled(),
            enable_l1=archive_ref_pick.l1_enabled(),
            enable_l2=archive_ref_pick.l2_enabled(),
            vision_fn=archive_ref_pick.cached_vision_fn(str(product_id or ""), task_kind),
            llm_fn=archive_ref_pick.production_llm_fn,
            deadline_ms=archive_ref_pick.deadline_ms())
    except HTTPException:
        raise
    except Exception as exc:  # 纯函数兜底：任何未预期异常都不阻断提交，走 forced0
        logger.warning("archive_ref_pick resolve failed: %s", type(exc).__name__)
        return PickResult([0], "forced0", f"自动优选异常（{type(exc).__name__}），回退主图 #0")
    logger.info("archive_ref_pick product=%s task=%s layer=%s indexes=%s reason=%s",
                product_id, task_kind, result.layer, result.indexes, result.reason)
    return result


def _pick_fields(pick: PickResult) -> dict:
    """提交响应/日志共用的可观测字段（selected_indexes / select_layer / select_reason）。"""
    return {"selected_indexes": list(pick.indexes), "select_layer": pick.layer,
            "select_reason": pick.reason[:200]}


@router.get("/products")
async def products_list(search: str = Query("", max_length=60),
                        x_evoflow_worker_key: str = Header(default="")) -> dict:
    _guard(x_evoflow_worker_key)
    try:
        data = ops_summary._authed_get("/api/product-assets")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="工作台商品档案暂不可用") from exc
    needle = search.strip().casefold()
    assets = []
    for row in data.get("assets") or []:
        if not isinstance(row, dict) or (needle and needle not in str(row.get("name") or "").casefold()):
            continue
        angles = row.get("view_angles") or []
        assets.append({"id": str(row.get("id") or ""),
                       "name": str(row.get("name") or "")[:80],
                       "selling_points": str(row.get("selling_points") or "")[:500],
                       "knowledge_id": str(row.get("knowledge_id") or ""),
                       "image_count": len(row.get("image_keys") or []),
                       "images": [{"index": i,
                                   "view_angle": str(angles[i] or "other") if i < len(angles) else "unmarked",
                                   "is_primary": i == 0}
                                  for i, _ in enumerate((row.get("image_keys") or [])[:60])]})
        if len(assets) >= 50:
            break
    return {"ok": True, "assets": assets}


@router.post("/images")
async def submit_image(payload: dict, x_evoflow_worker_key: str = Header(default="")) -> dict:
    _guard(x_evoflow_worker_key)
    ref = _ref(payload.get("external_ref"))
    prompt = str(payload.get("prompt") or "").strip()
    if len(prompt) < 8 or len(prompt) > 3000:
        raise HTTPException(status_code=400, detail="生图要求长度须为 8-3000 字")
    ratio = str(payload.get("ratio") or "3:4")
    if ratio not in _IMAGE_RATIOS:
        raise HTTPException(status_code=400, detail="图片比例无效")
    task_kind = ("image_detail" if str(payload.get("feature") or "").strip() == "detail"
                 else "image_main")
    explicit = payload.get("image_indexes")
    if isinstance(explicit, list) and explicit:
        # 显式指定（manual）：不跑自动；非法/多下标由 _asset 400，不静默改 0
        pick = PickResult(list(explicit), "manual", "用户显式指定档案参考图")
        logger.info("archive_ref_pick product=%s task=%s layer=manual indexes=%s",
                    payload.get("product_id"), task_kind, pick.indexes)
        asset, image_keys = _asset(payload.get("product_id"), pick.indexes)
    else:
        asset_row = _asset_row(payload.get("product_id"))
        pick = await asyncio.to_thread(_resolve_auto_pick, payload.get("product_id"),
                                       asset_row, task_kind=task_kind,
                                       want_count=1, prompt=prompt)
        asset, image_keys = _asset(payload.get("product_id"), pick.indexes, asset_row)
    if len(image_keys) != 1:
        raise HTTPException(status_code=400, detail="主图任务必须只选择 1 张商品参考图")
    params = {"images": image_keys, "requirement": prompt, "ratio": ratio,
              "reference_mode": "single", "product_id": str(asset.get("knowledge_id") or ""),
              "product_name": str(asset.get("name") or ""),
              "use_knowledge": bool(asset.get("knowledge_id"))}
    lock = _ref_locks.setdefault("image:" + ref, asyncio.Lock())
    async with lock:
        draft = ops_summary._authed_post("/api/records/draft", {
            "feature": "detail_main", "title": f"{asset.get('name') or '商品'}主图",
            "params": params, "external_ref": ref})
        rid = str(draft.get("id") or "")
        if not rid:
            raise HTTPException(status_code=502, detail="工作台未返回生图记录编号")
        record = None
        if draft.get("deduped"):
            try:
                record = ops_summary._authed_get("/api/records/" + quote(rid, safe=""))
            except Exception as exc:
                raise HTTPException(status_code=502,
                                    detail="原工单已登记但状态暂不可读；请勿再次提交") from exc
            if record.get("feature") != "detail_main":
                raise HTTPException(status_code=409, detail="该工单号已用于不同类型任务")
            old_params = record.get("params") or {}
            if any(old_params.get(key) != params.get(key)
                   for key in ("images", "requirement", "ratio", "product_id", "product_name", "use_knowledge")):
                raise HTTPException(status_code=409, detail="同一工单号已关联不同生图参数；请查询原记录，不要重复提交")
            if not record.get("items") and not record.get("running") and record.get("status") == "queued":
                try:
                    ops_summary._authed_post("/api/generate", {"rid": rid, "feature": "detail_main", "params": params})
                    record = ops_summary._authed_get("/api/records/" + quote(rid, safe=""))
                except Exception as exc:
                    raise HTTPException(status_code=502,
                                        detail="原工单仍待执行；提交结果不确定，请先查询状态") from exc
            replay = _safe_record(record, deduped=True)
            replay.update(_pick_fields(pick))
            return replay
        item = {"id": "evoflow-main-1", "label": "商品主图", "type": "main",
                "prompt": prompt, "status": "pending", "file": "", "error": "",
                "refs": image_keys, "source_image": image_keys[0], "reference_mode": "single"}
        try:
            ops_summary._authed_post("/api/generate", {
                "rid": rid, "feature": "detail_main", "params": params, "items": [item]})
        except Exception as exc:
            raise HTTPException(status_code=502,
                                detail="工单已登记，提交结果不确定；请先查询记录状态，不要创建新工单") from exc
        return {"ok": True, "id": rid, "title": f"{asset.get('name') or '商品'}主图",
                "status": "queued", "deduped": False, "items": [], **_pick_fields(pick)}


@router.get("/images/{record_id}")
async def image_status(record_id: str,
                       external_ref: str = Header(default="", alias="X-EvoFlow-External-Ref"),
                       x_evoflow_worker_key: str = Header(default="")) -> dict:
    _guard(x_evoflow_worker_key)
    if not _ID_RE.fullmatch(record_id) or not _REF_RE.fullmatch(external_ref):
        raise HTTPException(status_code=400, detail="记录 ID 格式无效")
    try:
        record = ops_summary._authed_get("/api/records/" + quote(record_id, safe=""))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="未找到工作台生图记录") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="工作台记录查询暂不可用") from exc
    if not hmac.compare_digest(str(record.get("external_ref") or ""), external_ref):
        raise HTTPException(status_code=404, detail="工作台记录与原工单号不匹配")
    return _safe_record(record)


@router.get("/video-options")
async def video_options(search: str = Query("", max_length=60),
                        x_evoflow_worker_key: str = Header(default="")) -> dict:
    _guard(x_evoflow_worker_key)
    try:
        data = ops_summary._authed_get("/api/video/creator/capabilities")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="工作台短视频模型清单暂不可用") from exc
    needle = search.strip().casefold()
    providers = []
    for provider in data.get("video_providers") or []:
        name = str(provider.get("name") or "")
        if needle and needle not in name.casefold():
            continue
        providers.append({"name": name, "models": [
            {"id": str(model.get("id") or ""),
             "durations": model.get("durations") or [],
             "ratios": model.get("ratios") or [],
             "resolutions": model.get("resolutions") or [],
             "max_images": int(model.get("max_images") or 1)}
            for model in (provider.get("models") or []) if isinstance(model, dict)
        ]})
    return {"ok": True, "providers": providers}


@router.post("/videos")
async def submit_video(payload: dict, x_evoflow_worker_key: str = Header(default="")) -> dict:
    _guard(x_evoflow_worker_key)
    ref = _ref(payload.get("external_ref"))
    prompt = str(payload.get("prompt") or "").strip()
    if len(prompt) < 8 or len(prompt) > 3000:
        raise HTTPException(status_code=400, detail="视频要求长度须为 8-3000 字")
    ratio = str(payload.get("ratio") or "9:16")
    if ratio not in _VIDEO_RATIOS:
        raise HTTPException(status_code=400, detail="视频比例无效")
    try:
        duration = int(payload.get("duration", 8))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="视频时长无效")
    provider = str(payload.get("provider") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not provider or not model:
        raise HTTPException(status_code=400, detail="必须先从工作台模型清单选择供应商和模型")
    submission_key = "evoflow:" + hashlib.sha256(ref.encode("utf-8")).hexdigest()[:48]
    try:
        capabilities = ops_summary._authed_get("/api/video/creator/capabilities")
        provider_row = next((row for row in capabilities.get("video_providers", [])
                             if str(row.get("name") or "") == provider), None)
        if not provider_row:
            raise HTTPException(status_code=400, detail="所选视频供应商当前不可用")
        model_row = next((row for row in provider_row.get("models", [])
                          if str(row.get("id") or "") == model), None)
        if not model_row:
            raise HTTPException(status_code=400, detail="所选视频模型当前不可用")
        resolution = str(payload.get("resolution") or "720p")
        for field, value in (("durations", duration),
                             ("ratios", ratio),
                             ("resolutions", resolution)):
            if value not in (model_row.get(field) or []):
                raise HTTPException(status_code=400, detail=f"当前视频模型不支持所选{field}")
        model_cap = max(1, int(model_row.get("max_images") or 1))
        explicit = payload.get("image_indexes")
        if isinstance(explicit, list) and explicit:
            # 显式指定（manual）：不跑自动；非法下标由 _asset 400，不静默改 0
            pick = PickResult(list(explicit), "manual", "用户显式指定档案参考图")
            logger.info("archive_ref_pick product=%s task=video layer=manual indexes=%s",
                        payload.get("product_id"), pick.indexes)
            asset, image_keys = _asset(payload.get("product_id"), pick.indexes)
        else:
            # 省略 indexes → 服务端自动优选（want_count 按模型上限截断）
            asset_row = _asset_row(payload.get("product_id"))
            want_count = min(3, model_cap)
            task_kind = "video_multi" if want_count > 1 else "video_cover"
            pick = await asyncio.to_thread(_resolve_auto_pick, payload.get("product_id"),
                                           asset_row, task_kind=task_kind,
                                           want_count=want_count, prompt=prompt)
            asset, image_keys = _asset(payload.get("product_id"), pick.indexes, asset_row)
        if len(image_keys) > model_cap:
            raise HTTPException(status_code=400, detail="参考图数量超过当前视频模型上限")
        config = {"provider": provider, "model": model,
                  "ratio": ratio, "resolution": resolution,
                  "duration": duration, "prompt": prompt,
                  "narration": str(payload.get("narration") or "")[:2000],
                  "external_ref": ref, "product_name": str(asset.get("name") or "")}
        data = ops_summary._authed_post("/api/video/creator/jobs", {
            "title": f"{asset.get('name') or '商品'}短视频", "image_keys": image_keys,
            "prompt": prompt, "narration": config["narration"], "config": config,
            "submission_key": submission_key})
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code,
                            detail="工作台拒绝了短视频参数；若提交结果不确定，请查询原工单") from exc
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail="短视频提交结果不确定；请先用同一工单号查询，不要生成新提交键") from exc
    return {**_safe_video(data), **_pick_fields(pick)}


@router.get("/videos/{job_id}")
async def video_status(job_id: str, x_evoflow_worker_key: str = Header(default="")) -> dict:
    _guard(x_evoflow_worker_key)
    if not _ID_RE.fullmatch(job_id):
        raise HTTPException(status_code=400, detail="视频任务 ID 格式无效")
    try:
        data = ops_summary._authed_get("/api/video/creator/jobs/" + quote(job_id, safe=""))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="未找到工作台短视频任务") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="工作台视频任务查询暂不可用") from exc
    return _safe_video(data)
