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
