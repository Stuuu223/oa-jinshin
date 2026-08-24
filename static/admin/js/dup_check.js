/* 录入前查重弹窗(客户录入页 change_form 引用):
   调 check_duplicates_view(只认高置信度:电话/公司名精确相同,泛称联系人不触发),
   有重复时弹自定义提示——按钮:「我已确认无撞单,继续录入」/「取消」.
   用户需求:低置信度(泛称王总)不提示;真撞单提示时需明确「我已确认无撞单」与「取消」. */
(function () {
  'use strict';

  function showDupDialog(lines) {
    var mask = document.createElement('div');
    mask.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:99999;display:flex;align-items:center;justify-content:center;';
    var box = document.createElement('div');
    box.style.cssText = 'background:#fff;border-radius:10px;padding:22px 26px;max-width:540px;width:90%;box-shadow:0 10px 30px rgba(0,0,0,.2);font-size:14px;';
    box.innerHTML =
      '<div style="font-size:16px;font-weight:600;color:#B45309;margin-bottom:10px">⚠ 录入信息与已有客户相同</div>' +
      '<pre style="white-space:pre-wrap;background:#FFF7ED;padding:10px;border-radius:6px;color:#475569;max-height:220px;overflow:auto;margin:0 0 14px">' + lines + '</pre>' +
      '<div style="font-size:13px;color:#64748B;margin-bottom:16px">本条信息依然会录入系统并做标识,请与公司总经办联系。</div>' +
      '<div style="text-align:right;display:flex;gap:10px;justify-content:flex-end">' +
      '<button id="dup-cancel" style="padding:8px 18px;border:1px solid #CBD5E1;border-radius:6px;background:#fff;cursor:pointer;color:#475569">取消</button>' +
      '<button id="dup-confirm" style="padding:8px 18px;border:none;border-radius:6px;background:#B45309;color:#fff;cursor:pointer">我已确认无撞单,继续录入</button>' +
      '</div>';
    mask.appendChild(box);
    document.body.appendChild(mask);
    return new Promise(function (resolve) {
      document.getElementById('dup-confirm').onclick = function () { document.body.removeChild(mask); resolve(true); };
      document.getElementById('dup-cancel').onclick = function () { document.body.removeChild(mask); resolve(false); };
    });
  }

  function onReady() {
    var form = document.querySelector('#customer_form');
    if (!form) return;
    form.addEventListener('submit', function (e) {
      var company = (document.querySelector('#id_company') || {}).value || '';
      var phone = (document.querySelector('#id_phone') || {}).value || '';
      if (!company && !phone) return; // 空值不查重
      e.preventDefault();
      var url = '/admin/customers/customer/check-duplicates/?company=' + encodeURIComponent(company) +
        '&phone=' + encodeURIComponent(phone);
      fetch(url).then(function (r) { return r.json(); }).then(function (data) {
        if (data.duplicates && data.duplicates.length) {
          var lines = data.duplicates.map(function (d) {
            return d.company + '（' + d.created_by + '录入,' + (d.match_fields || []).join('、') + '相同）';
          }).join('\n');
          showDupDialog(lines).then(function (ok) { if (ok) form.submit(); });
        } else {
          form.submit();
        }
      }).catch(function () { form.submit(); });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', onReady);
  } else { onReady(); }
})();
