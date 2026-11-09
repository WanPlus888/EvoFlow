/*
 * 工作台 SSO 垫片（1.4.18 运营终端账号默认 = 工作台账号）
 *
 * 由壳侧 Tauri `initialization_script_for_all_frames` 注入到 main 窗与运营
 * 悬浮窗的**所有 frame**。只在工作台 iframe（origin 必须
 * https://workbench.kll666.cn、直接父窗是壳）里生效，其余环境零影响：
 * 外部浏览器打开工作台时本脚本所有守卫均提前 return，
 * `window.pywebview` 不会被定义（AC7）。
 *
 * 工作台 web/app.js 已有「托盘单点登录」契约（pywebview）：
 *   - sso_login()            → {ok:true, token}（网页免登取令牌）
 *   - sso_save(origin, username, token, password)（网页登录后回推）
 * 本垫片把该契约桥接到父窗 postMessage，方向两条：
 *   工作台 → 壳：wb_token 出现/变化（'evoflow-wb-identity'）
 *     → 壳调网关 /api/webui/login-workbench-token 换壳 JWT → 账号跟随。
 *   壳 → 工作台：壳侧「切换用户」用工作台账密登录后种下 token
 *     （sso_login 应答 + 一次性 seed + reload，AC3）。
 * 密码永不出 iframe：sso_save 的 password 参数到此即弃，绝不转发。
 *
 * 纯 ES5 IIFE，无任何依赖；不使用 Tauri IPC（只 postMessage）。
 */
(function () {
  'use strict';

  /* ── 守卫（顺序即 fail-closed 顺序）────────────────────── */
  if (typeof window === 'undefined') return;
  try {
    if (window.top === window) return; // 只在 iframe 里活
    if (location.origin !== 'https://workbench.kll666.cn') return; // 只在工作台源
    if (window.parent !== window.top) return; // 只服务「直接父窗 = 壳顶层窗」的 iframe
  } catch (e1) {
    return;
  }
  var parentOrigin = '';
  try {
    parentOrigin = (location.ancestorOrigins && location.ancestorOrigins[0]) || '';
  } catch (e2) {
    parentOrigin = '';
  }
  /* 父源必须是壳自己：macOS 生产 tauri://localhost；Windows 生产
   * http(s)://tauri.localhost；Vite dev（steps 钉 1420 + 本仓实际 devUrl 1521）。
   * 其余（任何网站嵌工作台）一律不注入。 */
  if (!/^(tauri:\/\/localhost|https?:\/\/tauri\.localhost|http:\/\/(localhost:1420|localhost:1521|127\.0\.0\.1:1521))$/.test(parentOrigin)) return;
  /* 真托盘（pywebview 原生）优先，绝不覆盖。 */
  if (window.pywebview && window.pywebview.api) return;

  var MSG_SSO_REQUEST = 'evoflow-wb-sso-request';
  var MSG_SSO_REPLY = 'evoflow-wb-sso-reply';
  var MSG_IDENTITY = 'evoflow-wb-identity';
  var SEEDED_FLAG = 'ef-wb-sso-seeded';
  var WB_TOKEN_KEY = 'wb_token';

  /* 最近一次上报的 token（去重：与上次值相同不发，避免刷新工作台/切页噪音）。 */
  var lastIdentityToken = null;

  function postToParent(msg) {
    try {
      window.parent.postMessage(msg, parentOrigin);
    } catch (e) {
      /* ignore */
    }
  }

  function postIdentity(token, reason) {
    var t = token || null;
    if (t === lastIdentityToken) return;
    lastIdentityToken = t;
    postToParent({ type: MSG_IDENTITY, token: t, reason: reason });
  }

  /* ── sso_login：向父窗要壳侧已登录的工作台 token（3s 超时）── */
  function ssoLogin() {
    return new Promise(function (resolve) {
      var nonce = 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
      var done = false;
      var timer = setTimeout(function () {
        if (done) return;
        done = true;
        window.removeEventListener('message', onReply);
        resolve({ ok: false });
      }, 3000);
      function onReply(ev) {
        if (!ev || ev.source !== window.parent || ev.origin !== parentOrigin) return;
        var d = ev.data;
        if (!d || typeof d !== 'object' || d.type !== MSG_SSO_REPLY || d.nonce !== nonce) return;
        if (done) return;
        done = true;
        clearTimeout(timer);
        window.removeEventListener('message', onReply);
        if (typeof d.token === 'string' && d.token) resolve({ ok: true, token: d.token });
        else resolve({ ok: false });
      }
      window.addEventListener('message', onReply);
      postToParent({ type: MSG_SSO_REQUEST, nonce: nonce });
    });
  }

  /* ── sso_save：工作台登录成功回推（password 到此即弃，AC7）── */
  function ssoSave(origin, username, token, password) {
    /* eslint-disable no-unused-vars */
    var _origin = origin;
    var _username = username;
    var _password = password; // 密码永不出 iframe：只接收、不存、不转发
    /* eslint-enable no-unused-vars */
    if (token) postIdentity(String(token), 'login');
    return Promise.resolve(true);
  }

  window.pywebview = {
    api: {
      sso_login: ssoLogin,
      sso_save: ssoSave,
    },
  };

  /* ── 观察 wb_token：包装 Storage 原型（登录 / 换号 / 退出）── */
  try {
    var rawSetItem = Storage.prototype.setItem;
    var rawRemoveItem = Storage.prototype.removeItem;
    Storage.prototype.setItem = function (key, value) {
      var isWb;
      try {
        isWb = this === window.localStorage && key === WB_TOKEN_KEY;
      } catch (e) {
        isWb = false;
      }
      rawSetItem.call(this, key, value);
      if (isWb) postIdentity(value || null, 'change');
    };
    Storage.prototype.removeItem = function (key) {
      var isWb;
      try {
        isWb = this === window.localStorage && key === WB_TOKEN_KEY;
      } catch (e) {
        isWb = false;
      }
      rawRemoveItem.call(this, key);
      if (isWb) postIdentity(null, 'change');
    };
  } catch (e) {
    /* Storage 不可封装（异常环境）→ 只剩 boot / login 两条上报路径 */
  }

  /* ── 冷启（AC1 已登录老用户 / AC3 壳先登录）────────────── */
  function onReady(fn) {
    try {
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', fn);
        return;
      }
    } catch (e) {
      /* ignore */
    }
    fn();
  }

  onReady(function () {
    var bootToken = null;
    try {
      bootToken = window.localStorage.getItem(WB_TOKEN_KEY);
    } catch (e) {
      bootToken = null;
    }
    if (bootToken) {
      /* 已登录老用户冷启：直接上报，壳侧静默跟随（AC1）。 */
      postIdentity(bootToken, 'boot');
      return;
    }
    /* 工作台未登录：问父窗要壳侧 token，有则种下（一次性，AC3）。 */
    ssoLogin().then(function (r) {
      if (!r || !r.ok || !r.token) return;
      var seeded = false;
      try {
        seeded = window.sessionStorage.getItem(SEEDED_FLAG) === '1';
      } catch (e) {
        seeded = false;
      }
      if (seeded) return; // 防循环：只种一次
      try {
        window.sessionStorage.setItem(SEEDED_FLAG, '1');
      } catch (e) {
        /* ignore */
      }
      try {
        /* 与工作台 setToken 同格式（cookie 供同源 <img> 免 Bearer）。 */
        window.localStorage.setItem(WB_TOKEN_KEY, r.token);
        document.cookie =
          'wb_token=' + encodeURIComponent(r.token) +
          '; path=/; SameSite=Lax; max-age=2592000';
      } catch (e) {
        /* ignore */
      }
      location.reload();
    });
  });
})();
