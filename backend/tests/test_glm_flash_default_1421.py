"""1.4.21 壳默认模型 GLM-5.3-Flash 刀测例（网关/投影侧）。

覆盖 steps §6：
1. evopanel/VERSION == 1.4.21
2. 官方名单 / 面板快捷目录含 Flash（zhipu 预设）
3. 投影：仅配置智谱+小米、无会话覆盖的 fixture 下，Flash 进目录且 modelOrder
   flash 在前
4. 迁移：primary=mimo-v2.6-pro 且 Flash 在目录 → 迁 Flash；primary 已是用户
   其它模型 → 不变；primary 已是 Flash → 幂等不再写
5. 会话钉死不受影响（本刀逻辑不触碰会话存储——以迁移函数不写任何
   session 表为守卫断言）
6. Key 不回显：投影返回值与全部断言输出不含 api_key 字段/明文（假 Key 只
   检查「非空 + 指定长度 + 末四位掩码形式」）

DB 隔离：每例独立临时 EVOFLOW_HOME + EVOFLOW_DB_PATH + 全量 schema，
provider_config 走 EVOFLOW_ZCODE_PROVIDER_CONFIG 指向临时 fixture，
绝不触碰用户真实 ~/.zcode / ~/.evoflow。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, str(_BACKEND_ROOT / "packages" / "harness"))

_REPO_ROOT = _BACKEND_ROOT.parent

# 假 Key：仅用于长度/掩码断言，任何输出不得包含其明文。
FAKE_BIGMODEL_KEY = "sk-fake-bigmodel-key-0123456789abcdef"
FAKE_MIMO_KEY = "tp-fake-mimo-key-9876543210fedcba"


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """每个测试独立 EVOFLOW_HOME + EVOFLOW_DB_PATH，全量 schema。"""
    from evoflow.persistence import db as db_mod
    from evoflow.persistence.schema import ensure_app_schema

    home = tmp_path / "evoflow-home"
    home.mkdir()
    cfg_path = home / "config.yaml"
    cfg_path.write_text(
        "models: []\ntools: []\nsandbox:\n  use: evoflow.sandbox.noop:NoopSandboxProvider\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EVOFLOW_HOME", str(home))
    monkeypatch.setenv("EVOFLOW_DB_PATH", str(home / "evoflow.db"))
    monkeypatch.setenv("EVOFLOW_CONFIG_PATH", str(cfg_path))
    db_mod.reset_db_for_tests()
    conn = db_mod.get_db()
    ensure_app_schema(conn)
    yield home
    db_mod.reset_db_for_tests()


def _write_provider_config(tmp_path: Path, *, with_bigmodel: bool = True, default_model: dict | None = None) -> Path:
    """写一份结构对齐真实 ~/.zcode/v2/provider_config.json 的 fixture（假 Key）。"""
    rules: list[dict] = []
    if with_bigmodel:
        rules.append(
            {
                "providerId": "bigmodel-glm-coding-plan",
                "providerName": "智谱 GLM Coding Plan",
                "config": {
                    "group": "standard-personal",
                    "access": {"type": "api-key", "apiKey": FAKE_BIGMODEL_KEY},
                    "api": {
                        "type": "openai-chat-completions",
                        "baseUrl": "https://open.bigmodel.cn/api/coding/paas/v4",
                    },
                    "personalModelIds": ["glm-5.3-flash", "glm-5.3"],
                    "modelOrder": ["glm-5.3-flash", "glm-5.3"],
                },
            }
        )
    rules.append(
        {
            "providerId": "xiaomi-mimo-token-plan",
            "providerName": "小米 Mimo",
            "config": {
                "group": "standard-personal",
                "access": {"type": "api-key", "apiKey": FAKE_MIMO_KEY},
                "api": {
                    "type": "openai-chat-completions",
                    "baseUrl": "https://api.xiaomi-mimo.example/v1",
                },
                "personalModelIds": ["mimo-v2.6-pro", "mimo-v2.6-flash"],
                "modelOrder": ["mimo-v2.6-pro", "mimo-v2.6-flash"],
            },
        }
    )
    doc: dict = {
        "config": {
            "providerOrder": [r["providerId"] for r in rules],
            "providerConfigRules": {"providerRules": rules},
            "modelConfigRules": {
                "providerModelRules": [
                    {
                        "providerId": "bigmodel-glm-coding-plan",
                        "modelId": "glm-5.3-flash",
                        "config": {
                            "enabled": True,
                            "properties": {"inputFormat": {"supportsImage": True}},
                            "optionSpecs": {"reasoningLevel": {"values": ["low", "high", "max"]}},
                        },
                    },
                    {
                        "providerId": "bigmodel-glm-coding-plan",
                        "modelId": "glm-5.3",
                        "config": {
                            "properties": {"inputFormat": {"supportsPdf": True}},
                            "optionSpecs": {"reasoningLevel": {"values": ["high", "max"]}},
                        },
                    },
                ]
            },
            "defaultModelSelection": default_model,
        }
    }
    path = tmp_path / "provider_config.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def test_version_is_1421():
    version = (_REPO_ROOT / "evopanel" / "VERSION").read_text(encoding="utf-8").strip()
    assert version == "1.4.21"


def test_official_glm_ids_and_panel_preset_contain_flash():
    official = (_REPO_ROOT / "evopanel" / "src" / "zcode-shared" / "official-glm-model-id.ts").read_text(
        encoding="utf-8"
    )
    assert '"GLM-5.3-Flash"' in official
    assert '"GLM-5.3"' in official
    presets = (_REPO_ROOT / "evopanel" / "src" / "lib" / "model-presets.js").read_text(encoding="utf-8")
    assert "glm-5.3-flash" in presets


def test_projection_reads_bigmodel_only(tmp_path: Path):
    from evoflow.plans.zhipu_coding_plan_models import read_bigmodel_personal_providers

    cfg = _write_provider_config(tmp_path)
    providers = read_bigmodel_personal_providers(cfg)
    # 只投影智谱（bigmodel.cn）；小米/杂项供应商不进投影。
    assert [p["provider_id"] for p in providers] == ["bigmodel-glm-coding-plan"]
    provider = providers[0]
    assert provider["model_ids"] == ["glm-5.3-flash", "glm-5.3"]  # flash 排前
    # Key 只做非空 + 长度断言，不比对/输出明文
    assert len(provider["api_key"]) == len(FAKE_BIGMODEL_KEY)
    assert provider["api_key"][-4:] == FAKE_BIGMODEL_KEY[-4:]


def test_projection_skips_without_bigmodel(tmp_path: Path):
    from evoflow.plans.zhipu_coding_plan_models import read_bigmodel_personal_providers

    cfg = _write_provider_config(tmp_path, with_bigmodel=False)
    assert read_bigmodel_personal_providers(cfg) == []


def test_upsert_projects_flash_into_catalog(tmp_path: Path, isolated_db):
    from evoflow.persistence import config_repositories as cfg_repo
    from evoflow.plans.zhipu_coding_plan_models import upsert_zhipu_coding_plan_models

    cfg = _write_provider_config(tmp_path)
    result = upsert_zhipu_coding_plan_models(config_path=cfg)

    assert result["count"] == 2
    assert result["names"][0] == "glm-5.3-flash"
    rows = {r["name"]: r for r in cfg_repo.list_models()}
    flash = rows["glm-5.3-flash"]
    assert flash["vendor"] == "zhipu"
    assert flash["model"] == "glm-5.3-flash"
    assert flash["plan_type"] == "zhipu_coding_plan"
    assert flash["base_url"] == "https://open.bigmodel.cn/api/coding/paas/v4"
    # Key 非空 + 掩码式断言（长度/末四位），从不输出明文
    assert len(flash["api_key"]) == len(FAKE_BIGMODEL_KEY)
    assert flash["api_key"][-4:] == FAKE_BIGMODEL_KEY[-4:]
    # providerModelRules 生效：flash 支持图片输入、档位 low/high/max
    assert flash["supports_vision"] is True
    assert flash["thinking"]["supported_levels"] == ["low", "high", "max"]
    assert rows["glm-5.3"]["thinking"]["supported_levels"] == ["high", "max"]

    # 幂等：重复投影不增行、不改名
    again = upsert_zhipu_coding_plan_models(config_path=cfg)
    assert again["count"] == 2
    assert {r["name"] for r in cfg_repo.list_models()} == {"glm-5.3-flash", "glm-5.3"}

    # Key 不回显：投影返回结构不含任何凭证字段
    assert "api_key" not in json.dumps(result)
    assert FAKE_BIGMODEL_KEY not in json.dumps(result)
    assert FAKE_MIMO_KEY not in json.dumps(result)


def test_primary_migration_from_xiaomi_and_empty(tmp_path: Path, isolated_db):
    from evoflow.persistence import config_repositories as cfg_repo
    from evoflow.plans.zhipu_coding_plan_models import (
        migrate_primary_to_glm_flash,
        upsert_zhipu_coding_plan_models,
    )

    cfg = _write_provider_config(tmp_path)
    upsert_zhipu_coding_plan_models(config_path=cfg)

    # 空 primary → Flash
    assert cfg_repo.get_app_setting("primary_model") is None
    assert migrate_primary_to_glm_flash() == "glm-5.3-flash"
    assert cfg_repo.get_app_setting("primary_model") == "glm-5.3-flash"

    # 小米默认 → Flash
    cfg_repo.set_app_setting("primary_model", "mimo-v2.6-pro")
    assert migrate_primary_to_glm_flash() == "glm-5.3-flash"
    cfg_repo.set_app_setting("primary_model", "mimo-v2.6-flash")
    assert migrate_primary_to_glm_flash() == "glm-5.3-flash"

    # 已是 Flash → 幂等不再改写（返回 None 表示未动）
    assert migrate_primary_to_glm_flash() is None

    # 用户自选其它非小米默认 → 不抢
    cfg_repo.set_app_setting("primary_model", "my-own-model")
    assert migrate_primary_to_glm_flash() is None
    assert cfg_repo.get_app_setting("primary_model") == "my-own-model"


def test_primary_migration_without_flash_in_catalog(tmp_path: Path, isolated_db):
    from evoflow.persistence import config_repositories as cfg_repo
    from evoflow.plans.zhipu_coding_plan_models import migrate_primary_to_glm_flash

    cfg = _write_provider_config(tmp_path, with_bigmodel=False)
    # 目录无 Flash（未投影）→ 即便 primary 为小米默认也不迁移
    cfg_repo.set_app_setting("primary_model", "mimo-v2.6-pro")
    assert migrate_primary_to_glm_flash() is None
    assert cfg_repo.get_app_setting("primary_model") == "mimo-v2.6-pro"


def test_preferred_primary_fallback_guard():
    from evoflow.plans.zhipu_coding_plan_models import preferred_primary_fallback

    # 首项小米默认 + 目录有 Flash → Flash
    assert preferred_primary_fallback(["mimo-v2.6-pro", "glm-5.3-flash"]) == "glm-5.3-flash"
    # 首项正常模型 → 原样
    assert preferred_primary_fallback(["glm-5.3-flash", "mimo-v2.6-pro"]) == "glm-5.3-flash"
    assert preferred_primary_fallback(["a", "b"]) == "a"
    # 无 Flash 时小米首项不硬造
    assert preferred_primary_fallback(["mimo-v2.6-pro", "b"]) == "mimo-v2.6-pro"
    assert preferred_primary_fallback([]) is None


def test_migration_never_touches_session_storage(tmp_path: Path, isolated_db):
    """§3.5 守卫：迁移/投影只写 models 与 app_settings，不碰会话表。"""
    from evoflow.persistence import config_repositories as cfg_repo
    from evoflow.plans.zhipu_coding_plan_models import (
        migrate_primary_to_glm_flash,
        upsert_zhipu_coding_plan_models,
    )

    cfg = _write_provider_config(tmp_path)
    upsert_zhipu_coding_plan_models(config_path=cfg)
    migrate_primary_to_glm_flash()

    conn = cfg_repo.get_db()
    session_tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%session%'"
        ).fetchall()
    ]
    for table in session_tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count == 0, f"迁移不得写入会话表 {table}"


def test_no_plain_key_in_module_source():
    """自检：新模块源码不含任何真实/示例 Key 前缀以外的凭证字面量。"""
    src = (
        _BACKEND_ROOT
        / "packages"
        / "harness"
        / "evoflow"
        / "plans"
        / "zhipu_coding_plan_models.py"
    ).read_text(encoding="utf-8")
    assert "sk-" not in src.replace("sk-fake", "")
    assert "tp-" not in src
