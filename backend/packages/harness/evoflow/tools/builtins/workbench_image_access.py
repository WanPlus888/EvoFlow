"""Read workbench-owned image bytes on demand; never persist media in EvoFlow."""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

_IMAGE_REF_RE = re.compile(r"^workbench-image://([A-Za-z0-9_-]{1,100})/(0|[1-9][0-9]{0,2})/([A-Za-z0-9][A-Za-z0-9._-]{0,79})$")
_GATEWAY_PATH_RE = re.compile(r"^/api/opsboard/worker/images/[A-Za-z0-9_-]{1,100}/preview/(?:0|[1-9][0-9]{0,2})$")
_MAX_IMAGE_BYTES = 50 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def parse_workbench_image_ref(ref: str) -> tuple[str, int, str] | None:
    match = _IMAGE_REF_RE.fullmatch(str(ref or "").strip())
    return (match.group(1), int(match.group(2)), match.group(3)) if match else None


def _gateway_base() -> str:
    base = (os.getenv("EVOFLOW_GATEWAY_URL") or "http://127.0.0.1:8012").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Workbench image access requires the local Gateway")
    return base


def _gateway_request(path: str, *, preview_ref: str = "") -> tuple[bytes, str]:
    token = (os.getenv("EVOFLOW_WORKBENCH_TOOL_TOKEN") or "").strip()
    if not token or not _GATEWAY_PATH_RE.fullmatch(path):
        raise ValueError("Workbench image access is not configured")
    headers = {"X-EvoFlow-Worker-Key": token, "Accept": "image/*"}
    if preview_ref:
        match = _IMAGE_REF_RE.fullmatch(preview_ref)
        if not match:
            raise ValueError("Invalid Workbench image reference")
        headers["X-EvoFlow-Image-Ref"] = preview_ref
        headers["X-EvoFlow-External-Ref"] = match.group(3)
    request = urllib.request.Request(_gateway_base() + path, headers=headers)
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=25) as response:
            mime = str(response.headers.get("Content-Type") or "")
            if not mime.lower().startswith("image/"):
                raise ValueError("Workbench returned a non-image response")
            data = response.read(_MAX_IMAGE_BYTES + 1)
            if len(data) > _MAX_IMAGE_BYTES:
                raise ValueError("Workbench image exceeds the 50 MB limit")
            return data, mime
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Workbench image preview failed (HTTP {exc.code})") from None
    except (TimeoutError, OSError) as exc:
        raise ValueError(f"Workbench image preview unavailable ({type(exc).__name__})") from None


def read_workbench_image_ref(ref: str) -> tuple[bytes, str]:
    parsed = parse_workbench_image_ref(ref)
    if parsed is None:
        raise ValueError("Invalid Workbench image reference")
    record_id, index, _external_ref = parsed
    return _gateway_request(f"/api/opsboard/worker/images/{record_id}/preview/{index}",
                            preview_ref=ref)
