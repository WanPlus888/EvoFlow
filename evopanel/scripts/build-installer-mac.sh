#!/usr/bin/env bash
# EvoPanel macOS release: PyInstaller gateway -> Tauri DMG (same flow as build-installer-win.ps1).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVOPANEL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${EVOPANEL_DIR}/.." && pwd)"
MAC_BUILD_SCRIPT="${REPO_ROOT}/backend/packaging/macos/build-gateway-macos.sh"

echo "[build-installer-mac] evopanel: ${EVOPANEL_DIR}"
echo "[build-installer-mac] repo root: ${REPO_ROOT}"

if [[ ! -f "${MAC_BUILD_SCRIPT}" ]]; then
  echo "[build-installer-mac] ERROR: missing ${MAC_BUILD_SCRIPT}"
  exit 1
fi

# Sync version from evopanel/VERSION → package.json, Cargo.toml, tauri.conf.json
echo "[build-installer-mac] syncing version..."
node "${EVOPANEL_DIR}/scripts/sync-version.js"

BINARIES="${EVOPANEL_DIR}/src-tauri/binaries"
for legacy in \
  "${BINARIES}/evoflow-gateway.exe" \
  "${BINARIES}/backend-gateway.exe" \
  "${BINARIES}/backend-gateway-v2" \
  "${BINARIES}/evoflow-gateway-v2" \
  "${BINARIES}/backend-gateway"; do
  if [[ -e "${legacy}" ]]; then
    echo "[build-installer-mac] removing legacy: ${legacy}"
    rm -rf "${legacy}"
  fi
done

# Clean any stale gateway directory (e.g. Windows build artifacts from a
# previous cross-platform checkout) so they don't get bundled into the DMG.
GATEWAY_DIR_PRE="${EVOPANEL_DIR}/src-tauri/binaries/evoflow-gateway"
if [[ -d "${GATEWAY_DIR_PRE}" ]]; then
  echo "[build-installer-mac] cleaning stale gateway directory: ${GATEWAY_DIR_PRE}"
  rm -rf "${GATEWAY_DIR_PRE}"
fi

bash "${MAC_BUILD_SCRIPT}" "${EVOPANEL_DIR}/src-tauri/binaries/evoflow-gateway"

echo "[build-installer-mac] verifying gateway bundle..."
GATEWAY_DIR="${EVOPANEL_DIR}/src-tauri/binaries/evoflow-gateway"
GATEWAY_EXE="${GATEWAY_DIR}/evoflow-gateway"
if [[ ! -d "${GATEWAY_DIR}" ]]; then
  echo "[build-installer-mac] ERROR: gateway bundle directory not found at ${GATEWAY_DIR}"
  exit 1
fi
if [[ ! -f "${GATEWAY_EXE}" ]]; then
  echo "[build-installer-mac] ERROR: gateway executable missing at ${GATEWAY_EXE}"
  exit 1
fi
echo "[build-installer-mac] gateway bundle: ${GATEWAY_DIR} (dir)"
echo "[build-installer-mac] gateway executable: ${GATEWAY_EXE} ($(du -h "${GATEWAY_EXE}" | cut -f1))"

# --- Sidecar manifest pin (1.4.17): refuse to DMG a stale gateway bundle. ---
# Mirrors build-installer-win.ps1: sidecar-manifest panel_version must equal
# evopanel/VERSION. 1.4.16 shipped a 1.4.14 sidecar (login-workbench 404)
# because a stale binaries/evoflow-gateway was bundled; this gate fails fast.
MANIFEST_PATH="${GATEWAY_DIR}/sidecar-manifest.json"
EXPECTED_PANEL_VERSION="$(tr -d '[:space:]' < "${EVOPANEL_DIR}/VERSION")"
MANIFEST_PANEL_VERSION="$(node -e 'const fs=require("fs");const m=JSON.parse(fs.readFileSync(process.argv[1],"utf8"));process.stdout.write(String(m.panel_version||""))' "${MANIFEST_PATH}" 2>/dev/null || true)"
if [[ ! -f "${MANIFEST_PATH}" || -z "${MANIFEST_PANEL_VERSION}" ]]; then
  echo "[build-installer-mac] ERROR: sidecar manifest missing/unreadable at ${MANIFEST_PATH}"
  exit 1
fi
if [[ "${MANIFEST_PANEL_VERSION}" != "${EXPECTED_PANEL_VERSION}" ]]; then
  echo "[build-installer-mac] ERROR: sidecar-manifest panel_version='${MANIFEST_PANEL_VERSION}' != evopanel/VERSION='${EXPECTED_PANEL_VERSION}' (stale gateway bundle; rm -rf '${GATEWAY_DIR}' and rebuild)"
  exit 1
fi
echo "[build-installer-mac] sidecar pin ok: panel_version=${MANIFEST_PANEL_VERSION}"

# --- Login route smoke (1.4.17): frozen gateway must serve the 1.4.15 -------
# login-unification route. strings/rg cannot prove this (the PyInstaller PYZ
# archive is compressed), so boot the sidecar on a scratch port and require
# POST /api/webui/login-workbench to answer non-404: 401 = route present with
# wrong creds; 502/503 = route present but upstream unreachable — both pass.
# If this route is ever intentionally removed/renamed, update this probe.
HOST_ARCH="$(uname -m)"
GATEWAY_ARCHS="$(lipo -archs "${GATEWAY_EXE}" 2>/dev/null || true)"
cleanup_login_smoke() {
  if [[ -n "${SMOKE_PID:-}" ]]; then
    kill "${SMOKE_PID}" 2>/dev/null || true
    wait "${SMOKE_PID}" 2>/dev/null || true
  fi
  [[ -n "${SMOKE_LOG:-}" ]] && rm -f "${SMOKE_LOG}"
}
if [[ "${GATEWAY_ARCHS}" != *"${HOST_ARCH}"* ]]; then
  echo "[build-installer-mac] login route smoke: SKIP (binary arch [${GATEWAY_ARCHS}] not runnable on host ${HOST_ARCH}; cross build)"
elif [[ "${EVOFLOW_SKIP_LOGIN_SMOKE:-}" == "1" ]]; then
  echo "[build-installer-mac] login route smoke: SKIP (EVOFLOW_SKIP_LOGIN_SMOKE=1)"
else
  SMOKE_PORT="$(node -e 'const net=require("net");const s=net.createServer();s.listen(0,"127.0.0.1",()=>{console.log(s.address().port);s.close();});')"
  SMOKE_LOG="$(mktemp -t evoflow-gateway-smoke)"
  echo "[build-installer-mac] login route smoke: booting gateway on 127.0.0.1:${SMOKE_PORT}..."
  "${GATEWAY_EXE}" --mode gateway --port "${SMOKE_PORT}" >"${SMOKE_LOG}" 2>&1 &
  SMOKE_PID=$!
  trap cleanup_login_smoke EXIT
  smoke_up=0
  for _ in $(seq 1 45); do
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 2 "http://127.0.0.1:${SMOKE_PORT}/" 2>/dev/null || true)"
    if [[ -n "${code}" && "${code}" != "000" ]]; then
      smoke_up=1
      break
    fi
    if ! kill -0 "${SMOKE_PID}" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  if [[ "${smoke_up}" != "1" ]]; then
    echo "[build-installer-mac] ERROR: gateway never answered on scratch port; smoke log tail:"
    tail -5 "${SMOKE_LOG}" || true
    cleanup_login_smoke
    trap - EXIT
    exit 1
  fi
  route_code="$(curl -s -o /dev/null -w '%{http_code}' -m 15 -X POST "http://127.0.0.1:${SMOKE_PORT}/api/webui/login-workbench" -H 'Content-Type: application/json' -d '{"username":"build-smoke","password":"wrong"}' 2>/dev/null || true)"
  cleanup_login_smoke
  trap - EXIT
  if [[ "${route_code}" == "404" ]]; then
    echo "[build-installer-mac] ERROR: POST /api/webui/login-workbench -> 404 (login-unification route missing from frozen gateway; rebuild sidecar from current backend)"
    exit 1
  fi
  echo "[build-installer-mac] login route smoke ok: /api/webui/login-workbench -> ${route_code} (non-404)"
fi

cd "${EVOPANEL_DIR}"

# Wipe stale Vite output so orphaned public/ copies cannot re-enter the DMG.
if [[ -d "${EVOPANEL_DIR}/dist" ]]; then
  echo "[build-installer-mac] cleaning stale frontend dist/"
  rm -rf "${EVOPANEL_DIR}/dist"
fi

# Validate signing key length; disable updater artifacts if key is invalid.
# CI sets TAURI_SIGNING_PRIVATE_KEY from secret; if format/password is off,
# Tauri fails with "failed to decode secret key" *after* building the DMG.
NOCONFIG=""
SIGN_KEY="${TAURI_SIGNING_PRIVATE_KEY:-}"
if [[ -n "${SIGN_KEY}" ]]; then
  SIGN_KEY="$(echo "${SIGN_KEY}" | tr -d '[:space:]')"
fi
if [[ -n "${TAURI_SIGNING_PRIVATE_KEY_PATH:-}" ]]; then
  echo "[build-installer-mac] updater signing: TAURI_SIGNING_PRIVATE_KEY_PATH"
elif [[ -n "${SIGN_KEY}" && "${#SIGN_KEY}" -ge 280 && -n "${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}" ]]; then
  echo "[build-installer-mac] updater signing: env key (${#SIGN_KEY} chars, password set)"
elif [[ -n "${SIGN_KEY}" && "${#SIGN_KEY}" -ge 280 ]]; then
  echo "[build-installer-mac] signing key present but no password — disabling updater artifacts"
  NOCONFIG="--config=src-tauri/tauri.ci-nosign.conf.json"
  unset TAURI_SIGNING_PRIVATE_KEY
elif [[ -f "${EVOPANEL_DIR}/src-tauri/updater-signing.key" ]]; then
  export TAURI_SIGNING_PRIVATE_KEY_PATH="${EVOPANEL_DIR}/src-tauri/updater-signing.key"
  echo "[build-installer-mac] updater signing: ${TAURI_SIGNING_PRIVATE_KEY_PATH}"
else
  echo "[build-installer-mac] signing key unavailable — disabling updater artifacts"
  NOCONFIG="--config=src-tauri/tauri.ci-nosign.conf.json"
fi

# GHA macOS runners intermittently fail at hdiutil create with "Resource busy"
# (Spotlight / XProtect). Build .app once, then retry DMG-only with cleanup.
cleanup_hdiutil_state() {
  sync || true
  # Detach leftover volume mounts from a previous failed bundle_dmg.sh
  for mp in /Volumes/EvoFlow /Volumes/EvoFlow*; do
    if [[ -e "${mp}" ]]; then
      echo "[build-installer-mac] detaching leftover mount: ${mp}"
      hdiutil detach "${mp}" -force 2>/dev/null || true
    fi
  done
  # Stale read-write scratch images lock the next hdiutil create
  local target_root="${EVOPANEL_DIR}/src-tauri/target"
  if [[ -d "${target_root}" ]]; then
    find "${target_root}" \( -name 'rw.*.dmg' -o -name '.rw.*.dmg' \) -type f -delete 2>/dev/null || true
  fi
}

TAURI_BUILD_ARGS=(build --verbose)
if [[ -n "${NOCONFIG}" ]]; then
  TAURI_BUILD_ARGS+=("${NOCONFIG}")
fi
if [[ -n "${TAURI_BUILD_TARGET:-}" ]]; then
  echo "[build-installer-mac] tauri target: ${TAURI_BUILD_TARGET}"
  rustup target add "${TAURI_BUILD_TARGET}" 2>/dev/null || true
  TAURI_BUILD_ARGS+=(--target "${TAURI_BUILD_TARGET}")
fi

# macOS CI runners: vite build OOMs at Node's ~2GB default heap during transforming.
# Tauri beforeBuildCommand runs `npm run build`; raise heap for this process tree.
export NODE_OPTIONS="--max-old-space-size=8192"
echo "[build-installer-mac] NODE_OPTIONS=${NODE_OPTIONS}"

# --- DMG planning (manual bundle_dmg.sh, CJK-safe + sidecar-aware). -----------
# tauri 2.11.x `--bundles dmg` re-stages the .app (wiping manual sidecar
# injection) and tauri-build 2.6.2 cannot copy the large gateway dir as a
# resource (ENOTDIR). So: build .app → inject gateway → run tauri's own
# released bundle_dmg.sh by hand (same approach as tools/build-mac-dmg.sh).
PRODUCT_NAME="$(node -p "require('${EVOPANEL_DIR}/src-tauri/tauri.conf.json').productName")"
BUNDLE_ROOT="${EVOPANEL_DIR}/src-tauri/target"
if [[ -n "${TAURI_BUILD_TARGET:-}" ]]; then
  BUNDLE_ROOT="${BUNDLE_ROOT}/${TAURI_BUILD_TARGET}"
fi
BUILT_APP="${BUNDLE_ROOT}/release/bundle/macos/${PRODUCT_NAME}.app"
DMG_SCRIPT="${BUNDLE_ROOT}/release/bundle/dmg/bundle_dmg.sh"
DMG_ARCH="$(uname -m)"
if [[ "${DMG_ARCH}" == "arm64" ]]; then
  DMG_ARCH="aarch64"
elif [[ "${DMG_ARCH}" == "x86_64" ]]; then
  DMG_ARCH="x64"
fi
DMG_PATH="${BUNDLE_ROOT}/release/bundle/dmg/${PRODUCT_NAME}_${EXPECTED_PANEL_VERSION}_${DMG_ARCH}.dmg"

# bundle_dmg.sh is only released by tauri during a dmg bundling run. On a fresh
# checkout it does not exist yet — ask tauri to release it once (the run also
# rebuilds/clears the .app, so do this BEFORE the sidecar injection below).
if [[ ! -x "${DMG_SCRIPT}" ]]; then
  echo "[build-installer-mac] releasing tauri bundle_dmg.sh (one --bundles dmg run, failure tolerated)..."
  npm run tauri -- "${TAURI_BUILD_ARGS[@]}" --bundles dmg >/dev/null 2>&1 || true
fi
if [[ ! -x "${DMG_SCRIPT}" ]]; then
  echo "[build-installer-mac] ERROR: ${DMG_SCRIPT} not released by tauri (dmg bundle run failed?)"
  exit 1
fi

echo "[build-installer-mac] building .app (no dmg yet)..."
npm run tauri -- "${TAURI_BUILD_ARGS[@]}" --bundles app

# --- Sidecar post-install into the .app (1.4.17). -----------------------------
# Copy the freshly gated gateway into the .app Resources (tauri-build cannot do
# this itself), keep exec bits, then re-sign ad-hoc so Gatekeeper accepts the
# modified bundle. Mirrors the proven flow from tools/build-mac-dmg.sh.
if [[ ! -d "${BUILT_APP}" ]]; then
  echo "[build-installer-mac] ERROR: built .app not found at ${BUILT_APP}"
  exit 1
fi
APP_GATEWAY_DST="${BUILT_APP}/Contents/Resources/binaries/evoflow-gateway"
echo "[build-installer-mac] post-installing gateway sidecar into .app..."
rm -rf "${APP_GATEWAY_DST}"
mkdir -p "$(dirname "${APP_GATEWAY_DST}")"
cp -R "${GATEWAY_DIR}" "${APP_GATEWAY_DST}"
# 7z/cross-disk copies can drop exec bits — the gateway binary without +x
# fails to spawn and respawns forever.
chmod +x "${APP_GATEWAY_DST}/evoflow-gateway" 2>/dev/null || true
chmod -R +x "${APP_GATEWAY_DST}/tools" 2>/dev/null || true
APP_MANIFEST_VER="$(node -e 'const fs=require("fs");const m=JSON.parse(fs.readFileSync(process.argv[1],"utf8"));process.stdout.write(String(m.panel_version||""))' "${APP_GATEWAY_DST}/sidecar-manifest.json" 2>/dev/null || true)"
if [[ "${APP_MANIFEST_VER}" != "${EXPECTED_PANEL_VERSION}" ]]; then
  echo "[build-installer-mac] ERROR: sidecar copy into .app failed verification: panel_version='${APP_MANIFEST_VER}' != '${EXPECTED_PANEL_VERSION}'"
  exit 1
fi
echo "[build-installer-mac] in-app sidecar pin ok: panel_version=${APP_MANIFEST_VER}"
echo "[build-installer-mac] re-signing .app (ad-hoc)..."
if ! codesign --force --deep -s - "${BUILT_APP}" >/dev/null 2>&1; then
  echo "[build-installer-mac] ERROR: ad-hoc codesign failed for ${BUILT_APP}"
  exit 1
fi

DMG_ATTEMPTS="${TAURI_DMG_ATTEMPTS:-5}"
dmg_ok=0
for i in $(seq 1 "${DMG_ATTEMPTS}"); do
  cleanup_hdiutil_state
  if [[ "${i}" -gt 1 ]]; then
    delay=$(( (i - 1) * 8 ))
    echo "[build-installer-mac] DMG attempt ${i}/${DMG_ATTEMPTS} after ${delay}s (hdiutil Resource busy mitigation)..."
    sleep "${delay}"
  else
    echo "[build-installer-mac] bundling DMG via bundle_dmg.sh (attempt ${i}/${DMG_ATTEMPTS})..."
  fi
  STAGE="$(mktemp -d)"
  ditto "${BUILT_APP}" "${STAGE}/${PRODUCT_NAME}.app"
  rm -f "${DMG_PATH}"
  if bash "${DMG_SCRIPT}" --volname "${PRODUCT_NAME}" --hide-extension "${PRODUCT_NAME}.app" --app-drop-link 400 180 "${DMG_PATH}" "${STAGE}"; then
    dmg_ok=1
    rm -rf "${STAGE}"
    break
  fi
  rm -rf "${STAGE}"
  echo "[build-installer-mac] DMG attempt ${i} failed"
done

if [[ "${dmg_ok}" -ne 1 ]]; then
  echo "[build-installer-mac] ERROR: DMG bundling failed after ${DMG_ATTEMPTS} attempts (hdiutil Resource busy?)"
  exit 1
fi

echo "[build-installer-mac] DMG ready: ${DMG_PATH}"
echo "[build-installer-mac] done"
