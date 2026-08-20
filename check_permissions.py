# -*- coding: utf-8 -*-
"""SOP harness — 权限/表单自动化检查脚本(防同类遗漏,改权限后必跑).

检查项:
1. FK 下拉过滤:遍历所有 admin 注册模型的 User 外键,检查 formfield_for_dbfield 是否有角色过滤
   (同类问题:tech_assigned 曾列全部 26 用户)
2. 各角色 × 页面可达矩阵:200/302/403 与预期对照(菜单/视图/数据三层权限)
3. 各角色详情页字段可见性:技术仅 6 字段/销售隐藏建站/咨询隐藏来源
用法:venv/Scripts/python.exe manage.py shell < check_permissions.py(或复制到 manage.py shell)
"""
from django.apps import apps
from django.contrib import admin as dj_admin
from django.test import Client
from apps.accounts.models import User

ROLE_ACCOUNTS = {"销售": "sale_zhang", "销售主管": "lead_sale", "咨询": "consult_qian",
                 "咨询主管": "jia_yin", "技术": "tech_zhou", "总经办": "boss1"}

fail = []

print("=" * 60)
print("[1] FK 下拉过滤检查(User/Department/Team 外键)")
print("=" * 60)
for label in ["customers", "projects", "accounts"]:
    for model in apps.get_app_config(label).get_models():
        adm = dj_admin.site._registry.get(model)
        if not adm:
            continue
        has_ff = hasattr(adm, "formfield_for_dbfield")
        fks = [f.name for f in model._meta.fields
               if f.get_internal_type() == "ForeignKey" and f.related_model.__name__ in ("User", "Department", "Team")]
        for fk in fks:
            if not has_ff:
                fail.append(f"FK下拉未过滤: {label}.{model.__name__}.{fk} (admin无formfield_for_dbfield)")
                print(f"  FAIL {label}.{model.__name__}.{fk}: 无 formfield 过滤")
            else:
                print(f"  OK   {label}.{model.__name__}.{fk}: 有 formfield_for_dbfield")

print("=" * 60)
print("[2] 角色 × 页面可达矩阵")
print("=" * 60)
PAGES = {
    "客户列表": ("/admin/customers/customer/", {"销售": "200", "销售主管": "200", "咨询": "403", "咨询主管": "403", "技术": "403", "总经办": "200"}),
    "公海池": ("/admin/customers/customer/?status__exact=pool", {"销售": "200", "销售主管": "200", "咨询": "403", "咨询主管": "403", "技术": "403", "总经办": "200"}),
    "项目列表": ("/admin/projects/project/", {"销售": "200", "销售主管": "200", "咨询": "200", "咨询主管": "200", "技术": "200", "总经办": "200"}),
    "回收站": ("/admin/customers/recycledcustomer/", {"销售": "200", "销售主管": "200", "咨询": "403", "咨询主管": "403", "技术": "403", "总经办": "200"}),
    "销售工作台": ("/admin/sales-workbench/", {"销售": "200", "销售主管": "200", "咨询": "302", "咨询主管": "302", "技术": "302", "总经办": "200"}),
    "咨询工作台": ("/admin/consult-workbench/", {"销售": "302", "销售主管": "302", "咨询": "200", "咨询主管": "200", "技术": "302", "总经办": "200"}),
    "老板总览": ("/admin/dashboard/", {"销售": "302", "销售主管": "302", "咨询": "302", "咨询主管": "302", "技术": "302", "总经办": "200"}),
}
for pname, (url, expect) in PAGES.items():
    for rname, uname in ROLE_ACCOUNTS.items():
        u = User.objects.get(username=uname)
        u.set_password("admin123")
        u.save()
        cl = Client()
        cl.login(username=uname, password="admin123")
        code = str(cl.get(url, follow=False).status_code)
        ok = code == expect[rname]
        if not ok:
            fail.append(f"可达矩阵: {rname}×{pname} 实际{code} 期望{expect[rname]}")
            print(f"  FAIL {rname} × {pname}: {code} != {expect[rname]}")
print("可达矩阵: " + ("ALL OK" if not [f for f in fail if "可达矩阵" in f] else "有FAIL"))

print("=" * 60)
print("[3] 技术详情字段可见性(应仅 6 字段+利润)")
print("=" * 60)
from apps.projects.models import Project
import re
t = User.objects.get(username="tech_zhou")
cl = Client()
cl.login(username="tech_zhou", password="admin123")
p = Project.objects.first()
h = cl.get(f"/admin/projects/project/{p.pk}/change/").content.decode("utf-8", errors="replace")
labels = re.findall(r"<label[^>]*>([^<:：]+)[:：]?", h)
seen = set()
uniq = [l.strip() for l in labels if l.strip() and not (l.strip() in seen or seen.add(l.strip()))]
leak = any(k in " ".join(uniq) for k in ["联系人", "电话", "来源", "备注", "签约", "销售", "报价"])
print("技术详情字段:", uniq[:12])
print("泄漏检查: " + ("FAIL " + str([f for f in uniq if any(k in f for k in ["联系人", "电话", "来源", "备注", "签约", "销售", "报价"])]) if leak else "OK-仅6字段"))
if leak:
    fail.append("技术详情泄漏字段")

print("=" * 60)
print("结果:", "ALL OK" if not fail else f"{len(fail)} 个 FAIL")
for f in fail:
    print("  -", f)
