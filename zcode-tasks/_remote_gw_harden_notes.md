# 远端网关上产笔记 · gw-unauth-harden 1.4.20（刀 B）

> ZCode 只写不执行。上产等 **Jennifer 点名**，建议与刀 A（remote-gw-login-workbench，
> `20261109-remote-gw-login-workbench-steps.md`）**同一次远端操作**完成。

## 上产文件（相对 `/opt/evoflow/`）

| # | 本仓路径（tip `fix/gw-unauth-harden-1420`） | 远端目标 |
|---|---|---|
| 1 | `backend/packages/harness/evoflow/authz/http_guard.py` | `backend/packages/harness/evoflow/authz/http_guard.py` |
| 2 | `backend/packages/harness/evoflow/authz/context.py` | `backend/packages/harness/evoflow/authz/context.py` |
| 3 | `backend/app/gateway/routers/agents.py` | `backend/app/gateway/routers/agents.py` |
| 4 | `backend/app/gateway/routers/identity.py` | `backend/app/gateway/routers/identity.py` |
| 5 | （未抽 `request_signals.py`，无循环导入；models.py 未改逻辑不拷） | — |

## 流程（与刀 A 同一备份目录）

1. 备份上述 4 个远端现文件到备份目录（与刀 A 备份同处，记时间戳）。
2. 拷入 4 个文件。
3. systemd 追加环境变量（**必须带**——nginx 若某条代理未设 `X-Forwarded-For`，
   仅靠 env 兜底；见下）：

   ```
   # /etc/systemd/system/evoflow-gateway.service 的 [Service] 段追加
   Environment=EVOFLOW_DISABLE_UNAUTH_ADMIN=1
   ```

4. `systemctl daemon-reload && systemctl restart evoflow-gateway`。

## 验收（无 JWT、走公网 URL）

- `GET /api/identity/me` → `isOrgAdmin` 为 `false`
- `DELETE /api/agents/main` → 非 2xx（401/403）
- `POST /api/models`（空 body）→ **401**（不得 422）
- `POST /api/identity/principals/<pid>/promote-admin` → 401/403
- 回归：1.4.18 同步后的壳 JWT admin 用户仍可管理模型 / 删 agent

## 回滚

从备份目录拷回上述 4 文件、删除 `EVOFLOW_DISABLE_UNAUTH_ADMIN` 环境变量、restart。

## 备注 / 已知残留

- 本机 sidecar / `tauri dev` **不要**设该变量（保留单用户 bootstrap，开发体验不变）。
- `webui/middleware.py` 的 WebUI 页面级 gate 仍有 `is_local_request(client.host)`
  loopback 绕过（反代下恒真）——本刀不改（不在清单）；管理 API 面已由本刀关闭，
  页面级收紧留给后续刀。
- 无 JWT 的会话列表收紧为「local-admin 自己的历史」（principal 回落但 is_admin 已剥），
  属预期更安全行为。
