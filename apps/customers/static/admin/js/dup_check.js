/* 撞单录入前预检（细则第一页·六）：
   提交建档表单前按公司名/联系人/电话查重，命中则弹窗提醒，
   确认后本条信息依然录入系统并做标识。 */
(function () {
  var form = document.getElementById("customer_form");
  if (!form) return;
  var companyEl = document.getElementById("id_company");
  if (!companyEl) return;
  var contactEl = document.getElementById("id_contact_name");
  var phoneEl = document.getElementById("id_phone");

  function buildQuery() {
    var parts = [];
    [["company", companyEl], ["contact", contactEl], ["phone", phoneEl]].forEach(function (pair) {
      var value = (pair[1] && pair[1].value || "").trim();
      if (value) parts.push(pair[0] + "=" + encodeURIComponent(value));
    });
    return parts.join("&");
  }

  form.addEventListener("submit", function (e) {
    var qs = buildQuery();
    if (!qs) return;
    e.preventDefault();
    fetch("/admin/customers/customer/check-duplicates/?" + qs, {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" }
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var dups = (d && d.duplicates) || [];
        if (dups.length) {
          var names = dups.map(function (x) {
            // 标明'哪个同事'录入的:客户名(张三录入),owner为空时用录入人
            return x.company + "（" + (x.created_by || x.owner || "未知") + "录入）";
          }).join("、");
          if (!window.confirm(
            "与同事录入相同信息：" + names +
            "\n\n本条信息依然会录入系统并做标识，请与公司总经办联系。\n确定继续录入吗？"
          )) {
            return;
          }
        }
        form.submit(); // 原生 submit 不会再触发本监听器
      })
      .catch(function () { form.submit(); });
  });
})();
