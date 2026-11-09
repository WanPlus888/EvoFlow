# Mac 干净 worktree 上 `uv sync` 常见坑（出包笔记）

面向运维/开发在**全新 worktree**（或新机器）上装后端环境、出壳安装包。核心一句话：**先对 Python 小版本，再 `uv sync`**。1.4.13 出包时在干净 `wt-multi-bot-import-fix-1413` 上踩过，记录如下。

## 坑 1：`requires-python` 与本机/venv Python 不匹配 → sync 直接失败

- 后端 workspace 根 `backend/pyproject.toml` 要求 `requires-python = ">=3.12"`；harness 子包（`backend/packages/harness/pyproject.toml`）是 `>=3.10`。**以更严的 backend 根为准：3.12+**。
- 仓库已钉小版本：`backend/.python-version` = **3.12**。`uv` 在 `backend/` 下会自动按它选解释器。
- 干净 wt 常见的失败姿势：本机默认 `python3` 是 3.11（或自建了 3.13 的 venv）→ `uv sync` 报 requires-python 不满足。**不要**为迁就本机去放宽 `requires-python`。
- 绕过：`cd backend && uv python install 3.12` 后让 uv 自管 venv（删掉旧 `.venv` 重建），或 `uv venv --python 3.12` 再 `uv sync`。

## 坑 2：`tree-sitter-languages` 在 Apple Silicon (arm64) 缺轮子/编译失败

- 锁内钉版 `tree-sitter-languages==1.10.2`，其 macOS 轮子**只发 cp312**（arm64 有轮子但仅限 3.12）。用 3.11/3.13 会回退 sdist 源码编译，arm64 上常因缺 C 编译配置失败。
- 绕过（首选）：**就用仓库钉的 3.12**，直接命中 arm64 cp312 轮子，无需编译。
- 版本配套是刻意的（见 harness `pyproject.toml` 注释）：`tree-sitter-languages 1.10.x` 与 `tree-sitter>=0.22` API 不兼容，故钉 `tree-sitter>=0.21.3,<0.22` + `tree-sitter-languages>=1.10.2`（code_index AST 用，默认安装，与 uv sync / Docker / PyInstaller 一致）。**不要**擅自升级 tree-sitter 或删该依赖；确要跳过，按现网/运维惯用方式处理可选组，并以仓库现有 lock/注释为准。
- 另注意 `backend/pyproject.toml` 的 `[tool.uv] environments` 做了平台 fork（onnxruntime Intel/arm64 分钉），换机器架构时 sync 结果不同属预期。

## 建议流程（干净 wt 出包/跑点名测例）

```bash
# 1) 干净 worktree（不要复用带脏改动的旧 wt）
git worktree add ../wt-<topic> <base-sha>

# 2) 选对 Python（坑 1/2 一并规避）
cd backend && uv python install 3.12

# 3) 装依赖
uv sync

# 4) 点名测例（壳侧在 evopanel/，后端在 backend/）
cd ../evopanel && npx vitest run tests/ops-multi-bot-p0.test.js
cd ../backend && uv run pytest <点名文件> -q
```

之后按 [RELEASE.md](../../RELEASE.md) 出安装包；壳侧改动先过 `npx vitest run`（或点名套件）再出包。
