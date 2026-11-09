#!/usr/bin/env bash
# macOS 打包包装：绕过 Tauri 2.11.1 dmg 打包器在 CJK productName 下的 bug。
# 实测结论（2026-10-23）：productName 为中文时 `tauri build --bundles dmg` 在
# bundle_dmg.sh 步骤报 "failed to run"；同一脚本手动调用（中文 volname/中文 app）完全正常。
# 本脚本：先让 tauri 出 .app，再手动补 dmg。
set -euo pipefail

cd "$(dirname "$0")/../evopanel"
export PATH="${HOME}/.local/nodejs/bin:${HOME}/.cargo/bin:${PATH}"

VERSION=$(node -p "require('./package.json').version || '0.0.0'" 2>/dev/null || echo "0.0.0")
# tauri.conf 的 version 才是产品版本
VERSION=$(python3 -c "import json;print(json.load(open('src-tauri/tauri.conf.json'))['version'])")
PRODUCT=$(python3 -c "import json;print(json.load(open('src-tauri/tauri.conf.json'))['productName'])")

# ── 打包闸（1.4.17 防 1.4.16 旧 sidecar 复发）──────────────────────────────
# 1.4.16 事故：本脚本不重编网关，把 binaries/ 里残留的 1.4.14 旧网关装进了
# 1.4.16 的 .app → login-workbench 404。出 DMG 前双重断言：
#   ① sidecar-manifest panel_version 必须等于本版；
#   ② 冷启网关探针 POST /api/webui/login-workbench 不得 404（PYZ 压缩，strings 证不了）。
GW_DIR="src-tauri/binaries/evoflow-gateway"
GW_MANIFEST="${GW_DIR}/sidecar-manifest.json"
GW_EXE="${GW_DIR}/evoflow-gateway"
if [[ "${EVOFLOW_ALLOW_NO_GATEWAY:-}" == "1" ]]; then
  echo "⚠ EVOFLOW_ALLOW_NO_GATEWAY=1：跳过网关闸（仅供 UI 验证，严禁发版）"
else
  if [ ! -f "$GW_MANIFEST" ] || [ ! -f "$GW_EXE" ]; then
    echo "✗ 网关 sidecar 缺失（${GW_DIR}）。先跑 evopanel/scripts/build-installer-mac.sh 重编（或 backend/packaging/macos/build-gateway-macos.sh）；确要无网关 UI 验证包，设 EVOFLOW_ALLOW_NO_GATEWAY=1"
    exit 1
  fi
  GW_VER=$(python3 -c "import json;print(json.load(open('${GW_MANIFEST}'))['panel_version'])")
  if [ "$GW_VER" != "$VERSION" ]; then
    echo "✗ 残留旧网关：sidecar panel_version=${GW_VER} ≠ 本版 ${VERSION}（1.4.16 同款事故）。rm -rf ${GW_DIR} 后先跑 evopanel/scripts/build-installer-mac.sh"
    exit 1
  fi
  echo "✓ sidecar pin ok: panel_version=${GW_VER}"
  if lipo -archs "$GW_EXE" 2>/dev/null | tr ' ' '\n' | grep -qx "$(uname -m)"; then
    SMOKE_PORT=$(node -e 'const net=require("net");const s=net.createServer();s.listen(0,"127.0.0.1",()=>{console.log(s.address().port);s.close();});')
    SMOKE_LOG=$(mktemp -t gw-smoke)
    "$GW_EXE" --mode gateway --port "$SMOKE_PORT" >"$SMOKE_LOG" 2>&1 &
    SMOKE_PID=$!
    trap 'kill ${SMOKE_PID} 2>/dev/null || true; wait ${SMOKE_PID} 2>/dev/null || true; rm -f ${SMOKE_LOG:-}' EXIT
    smoke_up=0
    for _ in $(seq 1 45); do
      code=$(curl -s -o /dev/null -w '%{http_code}' -m 2 "http://127.0.0.1:${SMOKE_PORT}/" 2>/dev/null || true)
      if [ -n "$code" ] && [ "$code" != "000" ]; then smoke_up=1; break; fi
      kill -0 ${SMOKE_PID} 2>/dev/null || break
      sleep 1
    done
    if [ "$smoke_up" != "1" ]; then
      echo "✗ 网关探针起不来（日志尾）："; tail -5 "$SMOKE_LOG"; exit 1
    fi
    route_code=$(curl -s -o /dev/null -w '%{http_code}' -m 15 -X POST "http://127.0.0.1:${SMOKE_PORT}/api/webui/login-workbench" -H 'Content-Type: application/json' -d '{"username":"build-smoke","password":"wrong"}' 2>/dev/null || true)
    kill ${SMOKE_PID} 2>/dev/null || true; wait ${SMOKE_PID} 2>/dev/null || true
    if [ "$route_code" = "404" ]; then
      echo "✗ POST /api/webui/login-workbench → 404：网关缺登录统一路由（旧二进制）。rm -rf ${GW_DIR} 后重编"
      exit 1
    fi
    echo "✓ login 路由探针 ok：→ ${route_code}（非 404）"
    trap - EXIT
  else
    echo "⚠ 网关架构与主机不符（跨编译产物），跳过探针（manifest pin 仍生效）"
  fi
fi

echo "[build] tauri build（仅 .app）..."
npx tauri build --bundles app

APP="src-tauri/target/release/bundle/macos/${PRODUCT}.app"
DMG_DIR="src-tauri/target/release/bundle/dmg"
DMG="${DMG_DIR}/${PRODUCT}_${VERSION}_aarch64.dmg"
SCRIPT="${DMG_DIR}/bundle_dmg.sh"

if [ ! -d "$APP" ]; then echo "✗ 未找到 $APP"; exit 1; fi

# ── 网关 sidecar 后装（tauri-build 2.6.2 资源拷贝在大目录上报 ENOTDIR，绕开）──
GW_SRC="src-tauri/binaries/evoflow-gateway"
GW_DST="${APP}/Contents/Resources/binaries/evoflow-gateway"
if [ -d "$GW_SRC" ]; then
  echo "[build] 后装网关 sidecar → Resources/binaries/"
  rm -rf "$GW_DST"
  mkdir -p "$(dirname "$GW_DST")"
  cp -R "$GW_SRC" "$GW_DST"
  # 7z/跨盘拷贝可能丢可执行位——网关二进制丢了会 spawn 失败无限 respawn
  chmod +x "$GW_DST/evoflow-gateway" 2>/dev/null || true
  chmod -R +x "$GW_DST/tools" 2>/dev/null || true
  echo "[build] 重签名（ad-hoc）..."
  codesign --force --deep -s - "$APP" 2>&1 | tail -2
else
  echo "⚠ 未找到 ${GW_SRC}，打包将不含真网关（仅供 UI 验证）"
fi

if [ ! -x "$SCRIPT" ]; then
  # tauri 只在 dmg 目标下释放该脚本；首次手动打包时从 tauri crate 缓存里找不到就报错
  echo "✗ 未找到 ${SCRIPT}（先跑一次 npx tauri build --bundles dmg 让 tauri 释放脚本，允许其失败）"; exit 1
fi

STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
rm -f "$DMG"
echo "[build] 手动 bundle_dmg.sh → ${DMG}"
"$SCRIPT" --volname "$PRODUCT" --hide-extension "${PRODUCT}.app" --app-drop-link 400 180 "$DMG" "$STAGE"
rm -rf "$STAGE"

echo "[build] ✓ ${DMG}"
ls -la "$DMG"
