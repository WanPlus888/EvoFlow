#!/usr/bin/env python3
"""品牌换装 v2：全局词边界清扫「EvoFlow」→「电商运营终端」。

设计原则（合并上游的安全边界）：
- \\bEvoFlow\\b 词边界替换：不会碰 EvoFlowHomeDashboard 等标识符、evoflow/EVOFLOW 等其他大小写。
- 保护段：URL、EvovexAI/EvoFlow 归属引用（PolyForm Required Notice 要求保留）。
- 跳过 mirror-urls.js（REPO_MAP 的键是 GitHub 仓库真名，属于外部标识）。
- tauri.conf.json / tauri.macos.conf.json 走精确替换（不动 identifier/版权/许可证/updater pubkey）。
- 幂等：可重复执行；上游合并后重跑一次即可。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEW = "电商运营终端"

# 全局清扫范围（显示层代码/文档）
SWEEP_DIRS = ["evopanel/src", "skills"]
SWEEP_FILES = ["evopanel/index.html"]
SWEEP_EXTS = {".js", ".ts", ".tsx", ".jsx", ".svelte", ".html", ".md", ".json"}
SKIP_FILES = {
    "evopanel/src/lib/mirror-urls.js",   # REPO_MAP 键 = GitHub 仓库真名
}

# 保护段：命中后不参与替换（URL 与归属引用）
PROTECT = re.compile(
    r"(https?://[^\s\"'`)]+)"          # URL
    r"|(EvovexAI/EvoFlow)"              # 仓库归属引用
    r"|(github\.com/EvovexAI)"
)
WORD = re.compile(r"\bEvoFlow\b")


def brand_text(text: str) -> str:
    out = []
    last = 0
    for m in PROTECT.finditer(text):
        out.append(WORD.sub(NEW, text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(WORD.sub(NEW, text[last:]))
    return "".join(out)


def iter_targets():
    for rel in SWEEP_FILES:
        p = ROOT / rel
        if p.exists():
            yield p
    for rel in SWEEP_DIRS:
        d = ROOT / rel
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.is_file() and p.suffix in SWEEP_EXTS:
                yield p


def main() -> int:
    changed = 0
    for path in iter_targets():
        rel = str(path.relative_to(ROOT))
        if rel in SKIP_FILES:
            print(f"SKIP: {rel}")
            continue
        try:
            old = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = brand_text(old)
        if old != new:
            path.write_text(new, encoding="utf-8")
            changed += 1
    print(f"sweep: {changed} 个文件已换装")

    # tauri 配置：精确替换（幂等）
    pairs_global = [
        ('"productName": "EvoFlow"', f'"productName": "{NEW}"'),
        ('"title": "EvoFlow"', f'"title": "{NEW}"'),
        ('"shortDescription": "EvoFlow — AI Agent Orchestration Desktop"',
         f'"shortDescription": "{NEW} — AI 员工与电商生产编排工作台"'),
        ('"longDescription": "EvoFlow is a super agent orchestration framework powered by EvovexAI, featuring a visual management desktop panel built with Tauri v2."',
         f'"longDescription": "{NEW}：基于 EvoFlow（EvovexAI，PolyForm Noncommercial 授权）定制的智能体编排桌面工作台，内置 Tauri v2 面板。"'),
        ('"https://raw.githubusercontent.com/EvovexAI/EvoFlow/main/update/latest.json"',
         '"https://localhost/evoflow-fork-auto-update-disabled.json"'),
    ]
    for conf_rel in ("evopanel/src-tauri/tauri.conf.json", "evopanel/src-tauri/tauri.macos.conf.json"):
        conf = ROOT / conf_rel
        if not conf.exists():
            continue
        t = conf.read_text(encoding="utf-8")
        orig = t
        for o, n in pairs_global:
            t = t.replace(o, n)
        # 兜底：conf 里其余显示语义的 EvoFlow（保护 identifier/版权/URL 不动）
        t = brand_text(t)
        if t != orig:
            conf.write_text(t, encoding="utf-8")
            print(f"conf: {conf_rel} 已更新")
        import json
        json.loads(Path(conf).read_text(encoding="utf-8"))
        print(f"conf: {conf_rel} JSON OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
