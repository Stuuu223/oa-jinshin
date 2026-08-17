/* 金石系统 · 表单草稿自动保存（客户/项目表单）
   行为:
   - 输入防抖 800ms 后,把主表单(不含 inline/文件/密码框)序列化存入 localStorage;
   - 保存成功后自动清掉对应草稿;
   - 再次进入同一路径表单且存在 24h 内草稿 → 顶部黄条提示"恢复草稿/忽略";
   - "忽略"后本次会话(同一标签页)不再提示,且不再自动存草稿(直到用户再次输入)。
   边界: 仅恢复主表单字段;inline(跟进/附图等)行不入草稿。 */
(function () {
  var form = document.getElementById("customer_form") || document.getElementById("project_form");
  if (!form) return;

  var KEY = "jinshi-draft:" + location.pathname;
  var IGNORED_KEY = "jinshi-draft-ignored:" + location.pathname;
  var DRAFT_TTL = 24 * 60 * 60 * 1000; // 草稿 24 小时内有效
  var SKIP_TYPES = { file: 1, password: 1, hidden: 1, submit: 1, button: 1, reset: 1 };
  var banner = null;
  var saveTimer = null;
  var userEdited = false; // 用户是否真的输入过(忽略后不再自动存)

  // 诊断探针:状态挂到 <html data-draft-status>,排障时可从 DOM 读到
  function mark(status) {
    try { document.documentElement.setAttribute("data-draft-status", status); } catch (e) {}
  }
  mark("init");

  function isIgnored() {
    try { return sessionStorage.getItem(IGNORED_KEY) === "1"; } catch (e) { return false; }
  }

  function collect() {
    var data = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || SKIP_TYPES[el.type]) return;
      if (el.name.indexOf("__prefix__") >= 0) return; // inline 模板行
      if (/^(follow_ups|owner_history|attachments|payments|expenses|consultant_history)-/.test(el.name)) return; // inline 不入草稿
      data[el.name] = el.type === "checkbox" ? (el.checked ? "on" : "") : el.value;
    });
    return data;
  }

  function saveDraft() {
    try {
      var data = collect();
      var empty = true;
      for (var k in data) { if (data[k]) { empty = false; break; } }
      if (empty) { localStorage.removeItem(KEY); mark("cleared-empty"); return; }
      data.__savedAt = Date.now();
      localStorage.setItem(KEY, JSON.stringify(data));
      mark("saved");
    } catch (e) {
      mark("storage-error"); // 隐私模式/存储满:静默降级
    }
  }

  function bindAutosave() {
    form.addEventListener("input", function () {
      userEdited = true; // 用户真实输入 → 允许(重新)自动存
      clearTimeout(saveTimer);
      saveTimer = setTimeout(saveDraft, 800);
    });
    form.addEventListener("change", function () {
      userEdited = true;
      saveDraft();
    });
    window.addEventListener("beforeunload", saveDraft);
  }

  function savedJustNow() {
    // 兼容 stock Django(.messagelist .success)与 simpleui(可能用 .el-message--success / .messagelist li.success)
    return !!(document.querySelector(".messagelist .success, ul.messagelist li.success, .el-message--success, .alert-success"));
  }

  function applyDraft(data) {
    Object.keys(data).forEach(function (name) {
      if (name === "__savedAt") return;
      var el = form.elements[name];
      if (!el) return;
      if (el.type === "checkbox") { el.checked = data[name] === "on"; }
      else if (el.tagName === "SELECT" && el.multiple) { /* 多选暂不恢复 */ }
      else { el.value = data[name]; }
      try {
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } catch (e) {}
    });
  }

  function showRestoreBar(data) {
    banner = document.createElement("div");
    banner.style.cssText = "margin:10px 0;padding:10px 14px;border:1px solid #F59E0B;background:#FFFBEB;border-radius:8px;color:#92400E;font-size:13px;display:flex;gap:12px;align-items:center";
    var when = new Date(data.__savedAt).toLocaleString("zh-CN");
    banner.innerHTML = "检测到 " + when + " 未保存的草稿（" + countFilled(data) + " 个字段已自动暂存过）";
    var restore = document.createElement("button");
    restore.type = "button";
    restore.textContent = "恢复草稿";
    restore.style.cssText = "padding:4px 14px;background:#2563EB;color:#fff;border:none;border-radius:6px;cursor:pointer";
    restore.onclick = function () { applyDraft(data); removeBanner(); saveDraft(); };
    var drop = document.createElement("button");
    drop.type = "button";
    drop.textContent = "忽略";
    drop.style.cssText = "padding:4px 14px;background:#fff;color:#64748B;border:1px solid #CBD5E1;border-radius:6px;cursor:pointer";
    drop.onclick = function () {
      localStorage.removeItem(KEY);
      try { sessionStorage.setItem(IGNORED_KEY, "1"); } catch (e) {} // 本会话不再提示
      removeBanner();
      mark("ignored");
    };
    banner.appendChild(restore);
    banner.appendChild(drop);
    var content = document.querySelector("#content");
    if (content) {
      content.insertBefore(banner, content.firstChild);
    } else {
      form.parentNode.insertBefore(banner, form);
    }
  }

  function countFilled(data) {
    var n = 0;
    Object.keys(data).forEach(function (k) { if (k !== "__savedAt" && data[k]) n++; });
    return n;
  }

  function removeBanner() { if (banner && banner.parentNode) banner.parentNode.removeChild(banner); }

  if (savedJustNow()) {
    // 刚保存成功:清掉本页草稿,不再提示
    localStorage.removeItem(KEY);
    mark("cleared-saved");
  } else if (!isIgnored()) {
    var raw = null;
    try { raw = localStorage.getItem(KEY); } catch (e) { mark("storage-error"); }
    if (raw) {
      var data = null;
      try { data = JSON.parse(raw); } catch (e) {}
      if (data && data.__savedAt) {
        var age = Date.now() - data.__savedAt;
        if (age <= DRAFT_TTL) {
          showRestoreBar(data); // 仅 24h 内草稿提示,过期草稿视为无效
          mark("bar-shown");
        } else {
          localStorage.removeItem(KEY); // 过期草稿直接清除
          mark("expired-cleared");
        }
      } else {
        mark("bad-draft");
      }
    } else {
      mark("no-draft");
    }
  } else {
    mark("ignored-session"); // 本会话已忽略过,静默
  }
  bindAutosave();
})();
