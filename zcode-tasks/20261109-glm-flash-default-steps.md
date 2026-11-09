# 壳 1.4.21 · 运营大脑接入/露出 GLM-5.3-Flash + 默认模型从小米改 Flash

你是实施。**权威口径：本 steps 即任务单。** Jennifer 夜间待办：  
「GLM5.3Flash 的模型还没有加上去；目前默认模型还是小米——改成 Flash。」

**模型：GLM-5.3 · max。mode=yolo 仅限 wt 内改码/跑测。只出 tip；未审不装；禁 push；禁 DMG；禁碰工作台仓。**

---

## 0. 查清结论（2026-11-09 Asia/Shanghai 只读核实，steps 必须对准这些落点）

| 层 | 落点 | 现状 | 本刀是否改 |
|---|---|---|---|
| **运营大脑 UI 模型目录 / 默认选择** | 壳 `evopanel` 的 **zcode-provider** 体系；运行时个人配置 `~/.zcode/v2/provider_config.json` | 文件里已有个人供应商 `bigmodel-glm-coding-plan`（Base `https://open.bigmodel.cn/api/coding/paas/v4`），`personalModelIds/modelOrder` 含 `glm-5.3-flash` / `glm-5.3`，且 `defaultModelSelection` 已指向 `glm-5.3-flash` · reasoning `max`；同时仍挂着 `xiaomi-mimo-token-plan`（`mimo-v2.6-pro` / `mimo-v2.6-flash`） | **改代码侧的「默认策略 + 目录露出 + 启动迁移」**；**禁止**把含 Key 的 `provider_config.json` 提交进 git |
| **网关 primary_model / 连接** | `~/.evoflow/**/evoflow.db`：`evoflow_app_settings.primary_model`、`evoflow_models`、`evoflow_model_connections` | 本机 profile 库 `evoflow_models` **空**；`evoflow_model_connections` 仅见 **mimo** 连接 → Composer 容易回落到小米 | **要**：启动/迁移保证 Flash 进目录且 primary 优先 Flash；**禁**在 tip 里写死明文 Key |
| **官方 Coding Plan 规范 ID** | `evopanel/src/zcode-shared/official-glm-model-id.ts` | 已含 `GLM-5.3-Flash` / `GLM-5.3`（账号套餐用大写规范 ID） | 一般**不必改**；若账号套餐目录缺 Flash 再补 catalog 源 |
| **工作台 ANALYZE_PRESETS** | 工作台 `app/config.py` | 预设列表**已有**「智谱【GLM】 / GLM-5.3-Flash」且排在 mimo 前；那是工作台分析模型，**不是**运营大脑聊天默认 | **本刀不改工作台**（另案；勿混） |
| **ZCode 本机 defaultModelSelection** | 同上 `provider_config.json` | 已是 flash，但 Jennifer 仍见小米 → 说明 **App 运行时 primary / 会话钉死 / 连接目录** 未跟文件默认对齐 | 本刀修 **壳运行时对齐**，不是再改一份密钥文件入库 |

**结论：本刀落在壳仓（evopanel + 必要的 gateway/harness 默认与迁移），目标版本 1.4.21；不改工作台 1.23.x。**

---

## 1. 基线与 wt · 叠序

| 项 | 钉死 |
|---|---|
| **叠序** | `1.4.17`（tip `5c493df`）→ **`1.4.18` 账号同步** → **`1.4.19` 改名 AI 运营大脑** → **`1.4.20` 无鉴权硬化** → **本刀 `1.4.21` GLM-Flash 默认** |
| **父 tip** | **父=1.4.20 硬化审过 tip**。若硬化未出 tip：写明「父=1.4.20 审过 tip；叠序 1.4.18→1.4.19改名→1.4.20硬化→本刀1.4.21」并**停手回报**，勿抢在 1.4.18/19/20 wt 上改。严禁改动 `/Users/zhuhongfeng/wt-shell-account-sync-1418` / rename-1419 / harden-1420 |
| **新 wt** | `/Users/zhuhongfeng/wt-shell-glm-flash-default-1421` |
| **分支** | `feat/shell-glm-flash-default-1421` |
| **基线 VERSION** | 父 tip 的 `evopanel/VERSION`（应为 `1.4.20`） |
| **目标 VERSION** | **`1.4.21`**（`evopanel/VERSION` 及仓内与壳版本绑定的戳按现惯例同步；**勿**扫工作台 VERSION） |
| **模型** | ZCode **GLM-5.3** · reasoning **max** |
| **刀型** | **仅壳仓**；禁碰工作台任何 `wt-*` / `/opt/workbench` |

### 建 wt（等 1.4.20 硬化审过）

```bash
# 1) PARENT=<1.4.20 硬化审过 tip 全量 hash>
# 2) 从壳仓 git 根（与 1417/1418/1419/1420 同族）建 wt：
git worktree add -b feat/shell-glm-flash-default-1421 \
  /Users/zhuhongfeng/wt-shell-glm-flash-default-1421 \
  "$PARENT"
# 3) 本 steps 放进 wt 的 zcode-tasks/（或可读同路径）
# 4) 只在新 wt 改；禁进 wt-shell-account-sync-1418 / wt-shell-rename-1419 / harden-1420 工作区改码
```

只读参考（**勿**提交密钥、**勿** cat 回显 Key）：

- `~/.zcode/v2/provider_config.json`（结构：`providerOrder` / `providerConfigRules` / `defaultModelSelection`）
- `evopanel/src/zcode-provider-node/model-selection-config-repository.ts`
- `evopanel/src/react/hooks/useComposerModelCatalog.ts`（primary_model 回落）
- `backend/packages/harness/evoflow/admin/models.py`（`get_primary_model` / `set_primary_model`）
- `evopanel/src/zcode-shared/official-glm-model-id.ts`（已含 Flash）
- 本机 `~/.evoflow/profiles/default/data/app/evoflow.db` 表 `evoflow_model_connections`（现仅 mimo）

---

## 2. 硬禁（违反即失败）

1. **禁 `safe_deploy`**；禁替换远端网关 / 重启生产服务  
2. **未审不装**：不打 DMG、不覆盖 `/Applications`、不启动强改用户数据除非测例用临时 fixture  
3. **禁 `git push`**  
4. **禁碰工作台仓**（含 `新版工作台/wt-*`、`wt-redo-985-990-on-984`）  
5. **禁碰 #7 / 千川**  
6. **Key 不回显**：测例、日志、commit message、回报里**不得**出现 api_key / token 明文；断言只用「非空 / 长度 / 末四位掩码」类  
7. **禁止**把 `~/.zcode/v2/provider_config.json` 或含 Key 的用户库拷进仓库  
8. **禁止**删除用户小米供应商（可降默认优先级，但勿擅自删 Key/供应商）  
9. 不改 `identifier` / `com.evovex.evoflow` / `~/.evoflow` 路径名  
10. 入库注释勿写禁区部署脚本英文标识符字面  

---

## 3. 产品行为（钉死）

1. 运营大脑模型列表里**稳定可见**：`GLM-5.3-Flash`（及已有的 `GLM-5.3` / `glm-5.3-flash` 小写个人 ID，按现供应商类型显示，勿重复造第三套乱名）  
2. **新会话 / 无会话钉死模型时**：默认 = **Flash**（个人供应商 id `glm-5.3-flash`，或账号套餐规范 id `GLM-5.3-Flash`——与当前已登录/已配置的智谱通路一致；两者都在目录时优先 Flash）  
3. 若用户会话已显式钉死小米 → **不强制改历史会话**（避免悄悄换模型）；仅改「默认 / primary / 跟随智能体」回落  
4. 启动一次迁移（idempotent）：若 `primary_model` 为空或等于已知小米默认（`mimo-v2.6-pro` / `mimo-v2.6-flash`）且目录已有 Flash → 写为 Flash；**已是其它用户自选非小米默认则不抢**  
5. 智谱 Coding Plan Key / 个人 Key：**只走现有凭证存储**；本刀不打印、不迁移明文到新文件  

---

## 4. 改动白名单（按真实文件；实施前在父 tip 上再 `grep` 一次核对路径）

> 下列为核实后的主战场；若父 tip 结构微调，允许等价路径，但必须在回报列出最终路径。

### A. 默认选择与目录露出（evopanel）

| 区域 | 做什么 |
|---|---|
| zcode-provider 默认选择 | 保证解析序：`defaultModelSelection` → 若缺省或指向小米且 Flash 可用 → Flash；与 `model-selection-config-repository` / `providerProvisioning*` 对齐 |
| 内置/个人供应商模板或 catalog seed | 确保「智谱 Coding Plan / bigmodel」模板的 **builtin 或推荐 modelOrder 含 `glm-5.3-flash`（或规范 `GLM-5.3-Flash`）且排在默认候选前列**；小米模板可保留但不作为全局 default |
| Composer 回落 | `useComposerModelCatalog` / `defaultModelFromCatalog`：primary 与 catalog 同时存在 Flash 时，跟随智能体默认不得误选 mimo |
| 官方 ID | `official-glm-model-id.ts` 已含 Flash → **勿无故改名**；缺测则补「名单含 Flash」断言 |

### B. 网关 primary + 连接（backend / harness）

| 区域 | 做什么 |
|---|---|
| `set_primary_model` / 启动 hydrate | 增加 **idempotent 迁移**：条件见 §3.4；写入 `evoflow_app_settings.primary_model` |
| 模型目录同步 | 个人/账号供应商里的 Flash 必须出现在 `/api/models`（或 Tauri `listModels`）结果中；若现逻辑只把 `evoflow_model_connections` 里的连接列出来，则补「从 zcode-provider 已配置供应商投影到目录」的最小通路——**勿**只写死 mimo |
| 连接 | 可为 Flash 建/补 display 连接元数据；**api_key 从现有 credential store 读，禁止新造明文配置文件进 git** |

### C. VERSION / 测例

| 文件 | 改什么 |
|---|---|
| `evopanel/VERSION`（及壳内惯例联动戳） | → `1.4.21` |
| `backend/tests/test_glm_flash_default_1421.py`（新建）或 evopanel 侧等价测 | §5 |
| 连坐 | 与 VERSION / primary 默认硬编码冲突的旧测抬到 1.4.21 或改为读 VERSION |

### 不要改

- 工作台 `ANALYZE_PRESETS` / `app/config.py`  
- 1.4.18 账号同步行为、1.4.19 改名文案、1.4.20 无鉴权硬化（本刀叠在其后，勿回退）  
- 语音 Xiaomi pipeline（`speech/…/xiaomi_*`）——那是语音桥，与聊天默认模型无关  
- `#7` / 千川 / 工作台 FAB  

---

## 5. 详细步骤

### 步骤 0：基线核

```bash
cd /Users/zhuhongfeng/wt-shell-glm-flash-default-1421
test "$(cat evopanel/VERSION)" = "1.4.20"   # 或父 tip 宣称版本；不符停手
git rev-parse HEAD   # 必须 = 1.4.20 硬化审过 tip
git status           # 干净
```

### 步骤 1：摸清父 tip 上「目录从哪来」

在 wt 内只读：

```bash
grep -rn "defaultModelSelection\|primary_model\|mimo-v2.6\|glm-5.3-flash\|GLM-5.3-Flash" \
  evopanel/src/zcode-provider* evopanel/src/zcode-services/model-provider \
  evopanel/src/react/hooks/useComposerModelCatalog.ts \
  backend/packages/harness/evoflow/admin/models.py \
  backend/app/gateway/routers/models.py | head -80
```

把「列表组装函数」和「primary 读写」钉成改点；写入回报。

### 步骤 2：实现目录露出 + 默认 Flash

1. 模板/catalog：Flash 可见且可选  
2. 默认选择解析：无会话覆盖时 → Flash  
3. 迁移：§3.4  
4. **全程**日志用 `***` / 长度，不打 Key  

### 步骤 3：测例

见 §6。用临时目录 / mock store，**不要**读真实 `provider_config.json` 里的 Key 进断言输出。

### 步骤 4：VERSION

`evopanel/VERSION` → `1.4.21`；按壳惯例更新关联版本戳（与 1.4.18/19/20 steps 同一套，勿发明第三套）。

### 步骤 5：提交

单 tip 或少量逻辑提交 + 最终 release 戳提交；message **禁止**含 Key / 账号。

---

## 6. 测例清单

1. `evopanel/VERSION == 1.4.21`  
2. 官方名单或 catalog 源含 Flash（`GLM-5.3-Flash` 或 `glm-5.3-flash`）  
3. 默认解析：在「仅配置了智谱+小米、无会话覆盖」fixture 下，选出 Flash 而非 mimo  
4. 迁移：primary 为 `mimo-v2.6-pro` 且 Flash 在目录 → 迁移后 primary 为 Flash；primary 已是用户其它模型 → 不变  
5. 会话已钉死 mimo → 不在本刀逻辑里被改写（单测或注释+守卫）  
6. 任何测例 stdout/失败信息 **不含** `sk-` / `tp-` / 长 token  
7. diff 路径不涉及工作台仓、不涉及 `#7`/千川  

---

## 7. 验收命令（示例）

```bash
cd /Users/zhuhongfeng/wt-shell-glm-flash-default-1421
test "$(cat evopanel/VERSION)" = "1.4.21" && echo OK_VER
# 按仓内习惯：
cd backend && .venv/bin/pytest -q tests/test_glm_flash_default_1421.py
# 或 evopanel 侧 vitest/等价
git status
git log -1 --oneline
git diff --stat "$PARENT"
# 自检：回报前用 grep 扫即将粘贴的文本，确认无 api_key 明文
```

---

## 8. 完成回报（只交这些）

1. **tip** 短+全量 SHA；父 tip（应为 **1.4.20** 硬化审过 tip）  
2. wt 路径 + 分支；VERSION=`1.4.21`  
3. 最终改动文件列表 + 每个文件职责一句话  
4. §6 测例结果  
5. 确认句：目录可见 Flash；无会话覆盖时默认 Flash；不强制改历史钉死会话；Key 未回显；未碰工作台/1.4.18 wt；**未打 DMG / 未装 / 未 push**  
6. 若发现「账号套餐目录」与「个人 api-key 供应商」两套 ID（`GLM-5.3-Flash` vs `glm-5.3-flash`）的处理策略说明  

**不装、不上产、不 push、不打 DMG。** Jennifer 点名装机 / Windows 包另待办。

---

## 附：与邻刀关系

| 刀 | 关系 |
|---|---|
| 1.4.18 账号同步 | 先辈；**勿动**其 wt |
| 1.4.19 改名「AI 运营大脑」 | 先辈；**勿动**其 wt |
| 1.4.20 公网无鉴权硬化 | **直接父**（`20261109-gw-unauth-harden-steps.md` 已占 1.4.20）；本刀等其审过 tip |
| 工作台 986 / 987 | 并行；本刀零碰；工作台分析预设已有 GLM，不在本刀 |
| 远端网关升版 | 另 steps；本刀不替代 |
| Windows 安装包 | Jennifer 已进待办：壳相关收口后再打；**本刀不打** |

完。
