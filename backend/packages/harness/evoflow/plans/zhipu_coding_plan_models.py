"""智谱 Coding Plan / 个人 GLM 供应商 → 运营大脑目录投影（1.4.21 默认 Flash）.

运营大脑聊天的模型目录来自 ``evoflow_models``（Gateway /api/models），而用户在
设置里配好的智谱 Coding Plan / 个人 GLM 供应商存在 ZCode 个人供应商配置
（``~/.zcode/v2/provider_config.json``，现有凭证存储）。此前两套互不投影，
目录为空时 Composer 只能回落到旧连接残留的小米模型。

本模块在网关启动时做两件幂等的事：

1. **目录投影**：把已配置的智谱（bigmodel.cn）个人供应商的模型
   （``glm-5.3-flash`` / ``glm-5.3`` …）写进 ``evoflow_models``，
   ``plan_type=zhipu_coding_plan`` 标记来源；api_key 只在现有凭证存储
   （provider_config.json）与 ``evoflow_models`` 之间搬运，不打印、不落新文件。
2. **primary 迁移**：``evoflow_app_settings.primary_model`` 为空或等于已知小米
   默认（mimo-v2.6-pro / mimo-v2.6-flash）且目录已有 Flash → 写为 Flash；
   用户自选的其它非小米默认不抢。历史会话已钉死的 model_name 不在本模块管辖。

无 bigmodel 供应商配置时全部安静跳过（不造目录、不动 primary）。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

VENDOR_KEY = "zhipu"
PLAN_TYPE = "zhipu_coding_plan"
BIGMODEL_HOST_SUFFIX = "bigmodel.cn"

# 1.4.21 目标默认：GLM-5.3-Flash（个人小写 id / 套餐规范 id 两种拼法都认）。
GLM_FLASH_MODEL_IDS = ("glm-5.3-flash", "GLM-5.3-Flash")
# 已知小米默认 primary（历史装机残留），仅这两种允许被迁移到 Flash。
XIAOMI_DEFAULT_PRIMARY_IDS = frozenset({"mimo-v2.6-pro", "mimo-v2.6-flash"})

# 目录展示兜底（panel 快捷添加同源）；reasoning 档位优先从 provider_config 的
# providerModelRules 读取，读不到时用这份默认。
_DEFAULT_MODEL_META: dict[str, dict[str, Any]] = {
    "glm-5.3-flash": {
        "display_name": "GLM-5.3-Flash",
        "vision": True,
        "reasoning_levels": ["low", "high", "max"],
        "context_length": 200000,
    },
    "glm-5.3": {
        "display_name": "GLM-5.3",
        "vision": False,
        "reasoning_levels": ["high", "max"],
        "context_length": 200000,
    },
}


def is_glm_flash_model_id(model_id: str | None) -> bool:
    return str(model_id or "").strip().lower() == GLM_FLASH_MODEL_IDS[0]


def is_xiaomi_default_primary(name: str | None) -> bool:
    return str(name or "").strip().lower() in XIAOMI_DEFAULT_PRIMARY_IDS


def zcode_provider_config_path() -> Path:
    """ZCode 个人供应商配置路径；测试可用 ``EVOFLOW_ZCODE_PROVIDER_CONFIG`` 覆盖。"""
    override = str(os.getenv("EVOFLOW_ZCODE_PROVIDER_CONFIG") or "").strip()
    if override:
        return Path(override)
    return Path.home() / ".zcode" / "v2" / "provider_config.json"


def read_bigmodel_personal_providers(
    config_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """解析 provider_config.json 中已配置的智谱个人供应商。

    返回 ``[{provider_id, provider_name, base_url, api_key, model_ids}]``，
    ``model_ids`` 按 modelOrder（缺省 personalModelIds）排序。
    只挑 api.baseUrl 指向 bigmodel.cn 且模型非空的规则；其余供应商不投影。
    """
    path = Path(config_path) if config_path is not None else zcode_provider_config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        logger.warning("zcode provider config unreadable: %s", path, exc_info=True)
        return []

    config = raw.get("config") if isinstance(raw, dict) else None
    if not isinstance(config, dict):
        config = raw if isinstance(raw, dict) else {}
    rules_root = config.get("providerConfigRules")
    if isinstance(rules_root, dict):
        rules = rules_root.get("providerRules")
    else:
        rules = rules_root
    if not isinstance(rules, list):
        return []

    providers: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        body = rule.get("config") if isinstance(rule.get("config"), dict) else rule
        provider_id = str(rule.get("providerId") or body.get("providerId") or "").strip()
        api = body.get("api") if isinstance(body.get("api"), dict) else {}
        base_url = str(api.get("baseUrl") or api.get("base_url") or "").strip()
        access = body.get("access") if isinstance(body.get("access"), dict) else {}
        api_key = str(access.get("apiKey") or access.get("api_key") or "").strip()
        model_order = body.get("modelOrder")
        model_ids = (
            [str(m).strip() for m in model_order if str(m).strip()]
            if isinstance(model_order, list)
            else []
        )
        if not model_ids:
            personal = body.get("personalModelIds")
            if isinstance(personal, list):
                model_ids = [str(m).strip() for m in personal if str(m).strip()]
        if not provider_id or not base_url or not api_key or not model_ids:
            continue
        host = (urlparse(base_url).hostname or "").lower()
        if not host.endswith(BIGMODEL_HOST_SUFFIX):
            continue
        providers.append(
            {
                "provider_id": provider_id,
                "provider_name": str(rule.get("providerName") or provider_id),
                "base_url": base_url,
                "api_key": api_key,
                "model_ids": model_ids,
            }
        )
    return providers


def _model_meta(config_path: Path | str | None, provider_id: str, model_id: str) -> dict[str, Any]:
    """reasoning 档位 / 视觉能力优先读 providerModelRules，缺省用内置默认。"""
    meta = dict(_DEFAULT_MODEL_META.get(model_id.lower(), {}))
    meta.setdefault("display_name", model_id)
    meta.setdefault("vision", False)
    meta.setdefault("reasoning_levels", ["high", "max"])
    meta.setdefault("context_length", 200000)
    try:
        path = Path(config_path) if config_path is not None else zcode_provider_config_path()
        raw = json.loads(path.read_text(encoding="utf-8"))
        config = raw.get("config") if isinstance(raw.get("config"), dict) else raw
        mcr = config.get("modelConfigRules") if isinstance(config, dict) else None
        model_rules = mcr.get("providerModelRules") if isinstance(mcr, dict) else mcr
        if not isinstance(model_rules, list):
            return meta
        for rule in model_rules:
            if not isinstance(rule, dict):
                continue
            if str(rule.get("modelId") or "").lower() != model_id.lower():
                continue
            rule_provider = str(rule.get("providerId") or "").strip()
            if rule_provider and rule_provider != provider_id:
                continue
            cfg = rule.get("config") if isinstance(rule.get("config"), dict) else {}
            specs = cfg.get("optionSpecs") if isinstance(cfg.get("optionSpecs"), dict) else {}
            levels = (
                specs.get("reasoningLevel", {}).get("values")
                if isinstance(specs.get("reasoningLevel"), dict)
                else None
            )
            if isinstance(levels, list) and levels:
                meta["reasoning_levels"] = [str(v) for v in levels]
            props = cfg.get("properties") if isinstance(cfg.get("properties"), dict) else {}
            fmt = props.get("inputFormat") if isinstance(props.get("inputFormat"), dict) else {}
            if isinstance(fmt.get("supportsImage"), bool):
                meta["vision"] = fmt["supportsImage"]
            break
    except Exception:
        logger.debug("providerModelRules meta parse skipped", exc_info=True)
    return meta


def _resolve_config_name(model_id: str, existing: list[dict[str, Any]]) -> str:
    for row in existing:
        if str(row.get("vendor") or "") == VENDOR_KEY and str(row.get("model") or "") == model_id:
            return str(row.get("name") or model_id)
    names = {str(r.get("name") or "") for r in existing}
    if model_id not in names:
        return model_id
    candidate = f"{VENDOR_KEY}-{model_id}"
    if candidate not in names:
        return candidate
    i = 2
    while f"{candidate}-{i}" in names:
        i += 1
    return f"{candidate}-{i}"


def _model_document(
    *,
    name: str,
    provider: dict[str, Any],
    model_id: str,
    config_path: Path | str | None,
) -> dict[str, Any]:
    meta = _model_meta(config_path, provider["provider_id"], model_id)
    levels = [str(v) for v in meta["reasoning_levels"]]
    default_level = "max" if "max" in levels else (levels[-1] if levels else "high")
    doc: dict[str, Any] = {
        "name": name,
        "vendor": VENDOR_KEY,
        "model": model_id,
        "display_name": str(meta["display_name"]),
        "description": "智谱 Coding Plan（ZCode 个人供应商投影）",
        "use": "langchain_openai:ChatOpenAI",
        "base_url": provider["base_url"],
        "api_key": provider["api_key"],
        "supports_thinking": True,
        "supports_reasoning_effort": True,
        "supports_vision": bool(meta["vision"]),
        "context_length": int(meta["context_length"]),
        "input_context_length": int(meta["context_length"]),
        "output_context_length": 128000,
        "max_tokens": 128000,
        "request_timeout": 600,
        "max_retries": 2,
        "thinking": {
            "supported_levels": levels,
            "default_level": default_level,
            "default_mode": "auto",
        },
        "when_thinking_enabled": {"extra_body": {"thinking": {"type": "enabled"}}},
        "plan_type": PLAN_TYPE,
        "plan_config": {
            "catalog_id": "zhipu.coding_plan",
            "provider_id": provider["provider_id"],
            "model_id": model_id,
        },
    }
    return doc


def upsert_zhipu_coding_plan_models(
    *,
    config_path: Path | str | None = None,
) -> dict[str, Any]:
    """把已配置智谱供应商的模型幂等投影进 ``evoflow_models``。

    返回 ``{"count", "names", "providers"}``——不含任何 Key 材料，可安全打日志。
    """
    from evoflow.persistence import config_repositories as cfg_repo

    providers = read_bigmodel_personal_providers(config_path)
    names: list[str] = []
    existing = list(cfg_repo.list_models() or [])
    for provider in providers:
        for model_id in provider["model_ids"]:
            name = _resolve_config_name(model_id, existing)
            doc = _model_document(
                name=name,
                provider=provider,
                model_id=model_id,
                config_path=config_path,
            )
            cfg_repo.upsert_model(doc)
            existing = [r for r in existing if str(r.get("name") or "") != name]
            existing.append({"name": name, "vendor": VENDOR_KEY, "model": model_id})
            names.append(name)
    if names:
        logger.info(
            "zhipu coding-plan projection: %d models from %d providers",
            len(names),
            len(providers),
        )
    return {
        "count": len(names),
        "names": names,
        "providers": [p["provider_id"] for p in providers],
    }


def _find_flash_name(rows: list[dict[str, Any]]) -> str | None:
    """目录里找 GLM-5.3-Flash 行名；优先本投影（zhipu vendor / plan 标记）的行。"""
    fallback: str | None = None
    for row in rows:
        model_id = str(row.get("model") or "").strip()
        name = str(row.get("name") or "").strip()
        if not name or not is_glm_flash_model_id(model_id):
            continue
        if str(row.get("vendor") or "") == VENDOR_KEY or str(row.get("plan_type") or "") == PLAN_TYPE:
            return name
        if fallback is None:
            fallback = name
    return fallback


def migrate_primary_to_glm_flash(*, force: bool = False) -> str | None:
    """primary_model 为空或已知小米默认且目录有 Flash → 迁移为 Flash。幂等。

    ``force=True`` 仅供测例；正常启动路径永不强抢用户自选的非小米默认。
    返回迁移后的 primary 名；未迁移返回 None。
    """
    from evoflow.persistence import config_repositories as cfg_repo

    rows = list(cfg_repo.list_models() or [])
    flash_name = _find_flash_name(rows)
    if not flash_name:
        return None
    current = cfg_repo.get_app_setting("primary_model")
    current_text = str(current or "").strip()
    if force or not current_text or is_xiaomi_default_primary(current_text):
        cfg_repo.set_app_setting("primary_model", flash_name)
        logger.info(
            "primary model migrated to GLM-5.3-Flash (previous=%s)",
            current_text or "<empty>",
        )
        return flash_name
    return None


def preferred_primary_fallback(names: list[str]) -> str | None:
    """primary 缺失/失效时的目录首选：首项是小米默认且有 Flash → Flash。

    供 ``get_primary_model`` 读侧回落使用（迁移未跑或远端旧库时的兜底），
    不改任何持久值。
    """
    ordered = [str(n).strip() for n in names if str(n or "").strip()]
    if not ordered:
        return None
    first = ordered[0]
    if is_xiaomi_default_primary(first) or first.lower().startswith("mimo"):
        for name in ordered:
            if is_glm_flash_model_id(name):
                return name
    return first
