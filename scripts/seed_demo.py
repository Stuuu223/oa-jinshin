# -*- coding: utf-8 -*-
"""金石企服 v2 · 对准细则的演示数据脚本.

场景覆盖(对照《金石企服客户管理系统搭建细则》):
- 第一页:建档(各销售)、公海自动掉入、客户池广场释放/获取/署名、撞单提醒
- 第二页:成交→项目、咨询主管嘉茵分配/二次调配、收款/支出/利润

运行: venv/Scripts/python.exe manage.py shell -c "exec(open('scripts/seed_demo.py', encoding='utf-8').read())"
"""
import os
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
import django

django.setup()

from django.utils import timezone

from apps.accounts.models import Department, Notification, Role, Team, User
from apps.customers.models import (
    Customer, CustomerOwnerHistory, CustomerStatus, OwnerHistorySourceType, PoolType,
)
from apps.projects.models import (
    Project, ProjectConsultantHistory, ProjectExpense, ProjectPayment, SiteProgress,
)

# ────────────────────────────────────────────────────────────────────────────
# 组织与角色(对准细则:销售/销售主管/咨询师/咨询主管/技术/总经办)
# ────────────────────────────────────────────────────────────────────────────
dept_sales, _ = Department.objects.get_or_create(name="销售部")
dept_consult, _ = Department.objects.get_or_create(name="咨询部")
dept_tech, _ = Department.objects.get_or_create(name="技术部")
dept_boss, _ = Department.objects.get_or_create(name="总经办")

team_s1, _ = Team.objects.get_or_create(name="销售一组", department=dept_sales)
team_s2, _ = Team.objects.get_or_create(name="销售二组", department=dept_sales)
team_consult, _ = Team.objects.get_or_create(name="咨询组", department=dept_consult)

users_data = [
    # (username, real_name, role, dept, team, is_lead)
    ("boss1", "老板·张总", Role.ADMIN, dept_boss, None, False),
    ("boss2", "老板·李总", Role.ADMIN, dept_boss, None, False),
    ("sale_zhang", "销售·张三", Role.SALES, dept_sales, team_s1, False),
    ("sale_li", "销售·李四", Role.SALES, dept_sales, team_s1, False),
    ("sale_wang", "销售·王五", Role.SALES, dept_sales, team_s2, False),
    ("lead_sale", "主管·赵六", Role.SALES_LEAD, dept_sales, team_s1, True),
    ("consult_qian", "咨询·钱七", Role.CONSULTANT, dept_consult, team_consult, False),
    ("consult_sun", "咨询·孙八", Role.CONSULTANT, dept_consult, team_consult, False),
    ("jia_yin", "咨询主管·嘉茵", Role.CONSULTANT_LEAD, dept_consult, team_consult, True),
    ("tech_zhou", "技术·周九", Role.TECH, dept_tech, None, False),
]

users = {}
for username, real_name, role, dept, team, is_lead in users_data:
    u, created = User.objects.get_or_create(
        username=username,
        defaults=dict(real_name=real_name, role=role, department=dept, team=team,
                      is_team_lead=is_lead, is_staff=True, is_superuser=(role == Role.ADMIN)),
    )
    if not created:
        u.real_name, u.role, u.department, u.team, u.is_team_lead = real_name, role, dept, team, is_lead
        # 保证演示用户可登录 admin(is_staff),总经办为 superuser
        u.is_staff = True
        u.is_superuser = (role == Role.ADMIN)
        u.save()
    if not u.password or not u.has_usable_password():
        u.set_password("admin123")  # 兑现文末"密码均为 admin123"的承诺
        u.save()
    users[username] = u

team_s1.lead = users["lead_sale"]
team_s1.save()
team_s2.lead = None
team_s2.save()
team_consult.lead = users["jia_yin"]
team_consult.save()

print(f"✅ 组织与角色: {Department.objects.count()} 部门 / {Team.objects.count()} 团队 / {User.objects.count()} 用户")

# ────────────────────────────────────────────────────────────────────────────
# 第一页:客户建档(销售张三/李四/王五各自名下)
# ────────────────────────────────────────────────────────────────────────────
customers_data = [
    # (company, contact, phone, qual, source, quote, owner, status, note)
    ("杭州云启网络科技有限公司", "陈总", "13812340001", "ICPEDI", "转介绍", "50000", "sale_zhang", CustomerStatus.FOLLOWING, "意向强,已报价待回访"),
    ("深圳星澜文化传媒有限公司", "林总", "13812340002", "动漫网文", "主动咨询", "30000", "sale_zhang", CustomerStatus.FOLLOWING, "客户咨询动漫网文,需建站"),
    ("广州腾跃信息技术有限公司", "黄总", "13812340003", "ICP许可证", "广告投放", "20000", "sale_li", CustomerStatus.LEAD, "刚录入,未跟进"),
    ("北京聚梦科技有限公司", "何总", "13812340004", "EDI许可证", "转介绍", "45000", "sale_li", CustomerStatus.FOLLOWING, "平台型客户,需EDI"),
    ("成都繁星传媒有限公司", "邓总", "13812340005", "广播证", "主动咨询", "28000", "sale_wang", CustomerStatus.FOLLOWING, "广播电视节目制作"),
    ("武汉光谷数创科技有限公司", "朱总", "13812340006", "ICPEDI", "转介绍", "55000", "sale_wang", CustomerStatus.LEAD, "新客户待跟进"),
    # 公海客户(无归属,自动掉入)
    ("上海临港科信有限公司", "郭总", "13812340007", "ICP许可证", "广告投放", "18000", None, CustomerStatus.POOL, "30天未跟进自动掉入公海"),
    # 客户池广场客户(手动释放)
    ("苏州元澄网络科技有限公司", "马总", "13812340008", "动漫网文", "客户池广场", "32000", None, CustomerStatus.POOL, "由销售张三释放到客户池广场"),
]

customers = {}
for idx, (company, contact, phone, qual, source, quote, owner_key, status, note) in enumerate(customers_data):
    owner = users[owner_key] if owner_key else None
    c, _ = Customer.objects.update_or_create(
        company=company,
        defaults=dict(
            contact_name=contact, phone=phone, qualification_interest=qual,
            source=source, quote_amount=Decimal(quote), owner=owner,
            status=status, note=note, created_by=owner or users["sale_zhang"],
        ),
    )
    # 归属历史(栈底:建档记录)
    if not c.owner_history.exists():
        CustomerOwnerHistory.objects.create(
            customer=c, from_user=None, to_user=owner or users["sale_zhang"],
            source_type=OwnerHistorySourceType.DIRECT_INPUT,
            operator=owner or users["sale_zhang"], seq=1,
        )
    customers[company] = c

# 公海客户:记录 pool_type=AUTO + 入池时间
pool_c = customers["上海临港科信有限公司"]
pool_c.pool_type = PoolType.AUTO
pool_c.pool_entered_at = timezone.now()
pool_c.save()

# 客户池广场客户:pool_type=SQUARE + 释放人署名
square_c = customers["苏州元澄网络科技有限公司"]
square_c.pool_type = PoolType.SQUARE
square_c.square_released_by = users["sale_zhang"]
square_c.pool_entered_at = timezone.now()
square_c.save()
CustomerOwnerHistory.objects.create(
    customer=square_c, from_user=users["sale_zhang"], to_user=None,
    source_type=OwnerHistorySourceType.SQUARE, operator=users["sale_zhang"],
    seq=square_c.owner_history.count() + 1, source_note=users["sale_zhang"].real_name,
)

# 撞单场景:张三与李四都录了同一公司(不同电话,软查重命中公司名)
dup_c, _ = Customer.objects.update_or_create(
    company="杭州云启网络科技有限公司",
    defaults=dict(contact_name="陈总", phone="13812349999", qualification_interest="ICPEDI",
                  source="转介绍", quote_amount=Decimal("50000"), owner=users["sale_li"],
                  status=CustomerStatus.FOLLOWING, note="疑似撞单(与张三同名公司)", created_by=users["sale_li"]),
)
if not dup_c.owner_history.exists():
    CustomerOwnerHistory.objects.create(
        customer=dup_c, from_user=None, to_user=users["sale_li"],
        source_type=OwnerHistorySourceType.DIRECT_INPUT, operator=users["sale_li"], seq=1,
    )
# 撞单通知送总经办
for boss in [users["boss1"], users["boss2"]]:
    Notification.objects.get_or_create(
        recipient=boss, title="撞单提醒",
        defaults=dict(content=f"客户「杭州云启网络科技有限公司」疑似重复建档,请总经办核查。", link="/admin/customers/customer/"),
    )

print(f"✅ 客户档案: {Customer.objects.count()} 个(含 1 公海自动掉入 + 1 广场释放 + 1 撞单重复)")

# ────────────────────────────────────────────────────────────────────────────
# 第二页:成交→项目(销售张三成交1单 + 销售李四成交1单)
# ────────────────────────────────────────────────────────────────────────────
project_data = [
    # (customer_company, deal_business, contract_entity, invoiced, tax, quote, sales_key, site_category, site_info)
    ("杭州云启网络科技有限公司", "ICPEDI 双证办理", "杭州云启网络科技有限公司", True, True, "50000", "sale_zhang", "企业官网+备案", "官网设计开发,含ICP备案与EDI平台"),
    ("北京聚梦科技有限公司", "EDI 许可证办理", "北京聚梦科技有限公司", False, False, "45000", "sale_li", "交易平台", "在线交易平台搭建"),
]

projects = []
for company, business, entity, invoiced, tax, quote, sales_key, site_cat, site_info in project_data:
    src = customers[company]
    src.status = CustomerStatus.DEAL
    src.save()
    p, _ = Project.objects.update_or_create(
        company_snapshot=company,
        defaults=dict(
            customer=src, contact_name_snapshot=src.contact_name, phone_snapshot=src.phone,
            source_snapshot=src.get_source_display(), quote_amount=Decimal(quote),
            deal_business=business, contract_entity=entity,
            is_invoiced=invoiced, is_tax_included=tax,
            sales=users[sales_key], site_category=site_cat, site_info=site_info,
        ),
    )
    projects.append(p)

# 收款/支出/利润(咨询师填写)
p1, p2 = projects
ProjectPayment.objects.get_or_create(project=p1, amount=Decimal("30000"), defaults=dict(note="定金", recorded_by=users["consult_qian"]))
ProjectPayment.objects.get_or_create(project=p1, amount=Decimal("20000"), defaults=dict(note="尾款", recorded_by=users["consult_qian"]))
ProjectExpense.objects.get_or_create(project=p1, amount=Decimal("1200"), defaults=dict(note="域名费", recorded_by=users["consult_qian"]))
ProjectExpense.objects.get_or_create(project=p1, amount=Decimal("800"), defaults=dict(note="服务器费", recorded_by=users["consult_qian"]))
ProjectPayment.objects.get_or_create(project=p2, amount=Decimal("45000"), defaults=dict(note="全款", recorded_by=users["consult_sun"]))
ProjectExpense.objects.get_or_create(project=p2, amount=Decimal("1500"), defaults=dict(note="技术费", recorded_by=users["consult_sun"]))

# 咨询主管嘉茵分配 p1→钱七,p2→孙八(留痕)
for p, consult in [(p1, users["consult_qian"]), (p2, users["consult_sun"])]:
    if not p.consultant_history.exists():
        ProjectConsultantHistory.objects.create(
            project=p, from_consultant=None, to_consultant=consult,
            assigned_by=users["jia_yin"], seq=1,
        )
        p.consultant = consult
        p.save()

# 二次调配场景:p1 从钱七 → 孙八(嘉茵二次调配,留痕显示第一次=钱七)
p1.consultant = users["consult_sun"]
p1.save()
ProjectConsultantHistory.objects.create(
    project=p1, from_consultant=users["consult_qian"], to_consultant=users["consult_sun"],
    assigned_by=users["jia_yin"], seq=2,
)

# 技术进度(p1 建站中,p2 待开始)
p1.site_progress = SiteProgress.IN_PROGRESS
p1.save()

print(f"✅ 成交项目: {Project.objects.count()} 个(p1 利润={p1.profit},p2 利润={p2.profit})")
print(f"   分配历史: {ProjectConsultantHistory.objects.count()} 条(含嘉茵二次调配留痕)")
print(f"   收款 {ProjectPayment.objects.count()} 条 / 支出 {ProjectExpense.objects.count()} 条")

# ────────────────────────────────────────────────────────────────────────────
# 汇总
# ────────────────────────────────────────────────────────────────────────────
print("\n===== 演示数据就绪 =====")
print(f"用户 {User.objects.count()} / 团队 {Team.objects.count()} / 客户 {Customer.objects.count()} / 项目 {Project.objects.count()}")
print("测试账号(密码均为 admin123):")
print("  boss1/boss2 总经办 | sale_zhang/sale_li/sale_wang 销售 | lead_sale 销售主管")
print("  consult_qian/consult_sun 咨询 | jia_yin 咨询主管(嘉茵) | tech_zhou 技术")
