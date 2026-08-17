/* 金石系统 · 表单草稿自动保存（客户/项目表单）
   行为:
   - 输入防抖 800ms 后,把主表单(不含 inline/文件/密码框)序列化存入 localStorage;
   - 保存成功后跳转的页面带 success 提示 → 自动清掉对应草稿;
   - 再次进入未保存过的同一路径表单 → 顶部黄条提示"恢复草稿/忽略"。
   边界: 仅恢复主表单字段;inline(跟进/附图等)行不入草稿,仍依赖"保存并继续编辑"。 */
(function () {
  var form = document.getElementById("customer_form") || document.getElementById("project_form");
  if (!form) return;

  var KEY = "jinshi-draft:" + location.pathname;
  var SKIP_TYPES = { file: 1, password: 1, hidden: 1, submit: 1, button: 1, reset: 1 };
  var banner = null;
  var saveTimer = null;

  // 诊断探针:状态挂到 <html data-draft-status>,排障时可从 DOM 读到,不弹任何 UI
  function mark(status) {
    try { document.documentElement.setAttribute("data-draft-status", status); } catch (e) {}
  }
  mark("init");

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
      clearTimeout(saveTimer);
      saveTimer = setTimeout(saveDraft, 800);
    });
    form.addEventListener("change", saveDraft);
    // 兜底:切页/关页前立即落一次,不依赖防抖
    window.addEventListener("beforeunload", saveDraft);
  }

  function savedJustNow() {
    var ok = document.querySelector(".messagelist .success, ul.messagelist li.success");
    return !!ok;
  }

  function applyDraft(data) {
    Object.keys(data).forEach(function (name) {
      if (name === "__savedAt") return;
      var el = form.elements[name];
      if (!el) return;
      if (el.type === "checkbox") { el.checked = data[name] === "on"; }
      else if (el.tagName === "SELECT" && el.multiple) { /* 多选暂不恢复 */ }
      else { el.value = data[name]; }
      // 必须派发事件:simpleui/Vue 只在事件时同步内部状态,裸赋值会被回写覆盖
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
    drop.onclick = function () { localStorage.removeItem(KEY); removeBanner(); };
    banner.appendChild(restore);
    banner.appendChild(drop);
    // 插到 #content 内部顶端(simpleui 无 h1,此前插到容器外导致坐标点击落空)
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
    localStorage.removeItem(KEY);
    mark("cleared-saved");
  } else {
    var raw = null;
    try { raw = localStorage.getItem(KEY); } catch (e) { mark("storage-error"); }
    if (raw) {
      var data = null;
      try { data = JSON.parse(raw); } catch (e) {}
      if (data && data.__savedAt) {
        showRestoreBar(data);
        mark("bar-shown");
      } else {
        mark("bad-draft");
      }
    } else {
      mark("no-draft");
    }
  }
  bindAutosave();
})();
