#!/usr/bin/env python3
"""品牌换装：把显示层产品自称「EvoFlow」改为「电商运营终端」。

设计原则（合并上游的安全边界）：
- 只改用户可见的产品自称；不改包名/标识符/环境变量/数据库/URL。
- 许可证要求保留的 EvovexAI 归属引用（EvovexAI/EvoFlow、版权行、LICENSE/NOTICE）一律不碰。
- 本脚本可重复执行（幂等）；上游合并后重跑一次即可。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEW = "电商运营终端"

# 显示层文件白名单（相对 fork 根目录）
DISPLAY_FILES = [
    "evopanel/index.html",
    "evopanel/src/pages/login.js",
    "evopanel/src/pages/about.js",
    "evopanel/src/pages/about-update.js",
    "evopanel/src/pages/project-detail.js",
    "evopanel/src/pages/settings/meta.js",
    "evopanel/src/components/sidebar.js",
    "evopanel/src/components/engagement.js",
    "evopanel/src/main.js",
    "evopanel/src/lib/page-help.js",
    "evopanel/src/locales/modules/chat-debug.js",
    "evopanel/src/locales/modules/channels.js",
    "evopanel/src/locales/modules/settings.js",
    "evopanel/src/locales/modules/dashboard.js",
    "skills/public/evoflow-admin/SKILL.md",
    "skills/public/evoflow-admin/references/product-intro.md",
    "skills/public/evoflow-admin/references/assets-contract.md",
]

# 保护段：命中后不参与替换（URL 与归属引用）
PROTECT = re.compile(
    r"(https?://[^\s\"'`)]+)"          # URL
    r"|(EvovexAI/EvoFlow)"              # 仓库归属引用
    r"|(github\.com/EvovexAI)"
)


def brand_text(text: str) -> str:
    out = []
    last = 0
    for m in PROTECT.finditer(text):
        out.append(text[last:m.start()].replace("EvoFlow", NEW))
        out.append(m.group(0))
        last = m.end()
    out.append(text[last:].replace("EvoFlow", NEW))
    return "".join(out)


def main() -> int:
    changed = []
    for rel in DISPLAY_FILES:
        path = ROOT / rel
        if not path.exists():
            print(f"SKIP missing: {rel}")
            continue
        old = path.read_text(encoding="utf-8")
        new = brand_text(old)
        if old != new:
            path.write_text(new, encoding="utf-8")
            changed.append(rel)
            print(f"BRANDED: {rel} ({old.count('EvoFlow') - new.count('EvoFlow')} 处)")
        else:
            print(f"no-change: {rel}")

    # tauri.conf.json：精确替换（不动 identifier / 版权 / 许可证 / updater pubkey）
    conf = ROOT / "evopanel/src-tauri/tauri.conf.json"
    t = conf.read_text(encoding="utf-8")
    pairs = [
        ('"productName": "EvoFlow"', f'"productName": "{NEW}"'),
        ('"title": "EvoFlow"', f'"title": "{NEW}"'),
        ('"shortDescription": "EvoFlow — AI Agent Orchestration Desktop"',
         f'"shortDescription": "{NEW} — AI 员工与电商生产编排工作台"'),
        ('"longDescription": "EvoFlow is a super agent orchestration framework powered by EvovexAI, featuring a visual management desktop panel built with Tauri v2."',
         f'"longDescription": "{NEW}：基于 EvoFlow（EvovexAI，PolyForm Noncommercial 授权）定制的智能体编排桌面工作台，内置 Tauri v2 面板。"'),
        # 禁用上游自动更新（防定制被官方新版本覆盖）
        ('"https://raw.githubusercontent.com/EvovexAI/EvoFlow/main/update/latest.json"',
         '"https://localhost/evoflow-fork-auto-update-disabled.json"'),
    ]
    for o, n in pairs:
        if o in t:
            t = t.replace(o, n)
            print(f"conf: replaced [{o[:50]}...]")
        else:
            print(f"conf: NOT FOUND [{o[:50]}...]")
    conf.write_text(t, encoding="utf-8")
    changed.append("evopanel/src-tauri/tauri.conf.json")

    print(f"\nTOTAL files changed: {len(changed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
