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
          // 组装'你填的哪项=值':让用户一眼看到自己填了什么与已有客户相同
          var mine = [];
          [["公司名", companyEl], ["联系人", contactEl], ["电话", phoneEl]].forEach(function (pair) {
            var v = (pair[1] && pair[1].value || "").trim();
            if (v) mine.push(pair[0] + "「" + v + "」");
          });
          var mineText = mine.length ? mine.join("、") : "输入的信息";
          var names = dups.map(function (x) {
            var who = x.created_by || x.owner || "未知";
            var same = (x.match_fields && x.match_fields.length) ? x.match_fields.join("、") : "信息";
            return x.company + "（" + who + "录入，" + same + "相同）";
          }).join("、");
          if (!window.confirm(
            "你填的" + mineText + " 与已有客户相同：\n" + names +
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
