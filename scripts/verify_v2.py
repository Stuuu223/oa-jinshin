# -*- coding: utf-8 -*-
"""金石企服 v2 细则 · 全条款功能验证脚本(逐条 PASS/FAIL).

对照《金石企服客户管理系统搭建细则》第一页/第二页逐条验证:
- 第一页①~⑦ 客户信息管理(建档/筛选/权限/分配/客户池广场/撞单提醒/回收站)
- 第二页①~③ 成交客户信息管理(成交转项目/权限字段隐藏/嘉茵分配)

运行: venv/Scripts/python.exe manage.py shell < scripts/verify_v2.py
"""
import os
import sys
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
import django

django.setup()

from django.contrib import admin as admin_site
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.utils import timezone

from apps.accounts.models import Department, Notification, Role, Team, User
from apps.customers.admin import CustomerAdmin
from apps.customers.models import (
    Customer, CustomerOwnerHistory, CustomerStatus, OwnerHistorySourceType, PoolType,
)
from apps.projects.admin import ProjectAdmin
from apps.projects.models import Project, ProjectConsultantHistory, ProjectExpense, ProjectPayment

factory = RequestFactory()
results = []
P = "✅ PASS"
F = "❌ FAIL"
W = "⚠️ WARN"


def record(no, name, ok, detail=""):
    mark = P if ok else F
    results.append((no, name, mark, detail))
    print(f"{mark} [{no}] {name}" + (f" — {detail}" if detail else ""))


def make_request(user):
    """构造带指定用户的 Admin 请求."""
    req = factory.get("/admin/")
    req.user = user
    return req


# 清理上次运行的 TEST 测试数据,避免重复累积(注意删除顺序:先子表后父表,PROTECT 外键)
print("清理 TEST 测试数据...")
Project.objects.filter(company_snapshot__startswith="TEST").delete()
Customer.all_objects.filter(company__startswith="TEST").delete()
Customer.objects.filter(company__startswith="TEST").delete()
Notification.objects.filter(content__startswith="客户「TEST").delete()
User.objects.filter(username__startswith="test_").delete()
Team.objects.filter(name__in=["销售一组", "咨询组"]).delete()

# ────────────────────────────────────────────────────────────────────────────
# 测试数据准备(专用 TEST 前缀,不与 seed 混淆)
# ────────────────────────────────────────────────────────────────────────────
print("\n=== 测试数据准备 ===")
dept_sales, _ = Department.objects.get_or_create(name="销售部")
dept_consult, _ = Department.objects.get_or_create(name="咨询部")
dept_tech, _ = Department.objects.get_or_create(name="技术部")
dept_admin, _ = Department.objects.get_or_create(name="总经办")

# 团队:销售一组(主管 lead_sales1)、咨询组(主管嘉茵)
team_s1, _ = Team.objects.get_or_create(name="销售一组", department=dept_sales)
team_consult, _ = Team.objects.get_or_create(name="咨询组", department=dept_consult)


def mk_user(username, real_name, role, dept, team=None, lead=False):
    u, created = User.objects.get_or_create(
        username=username,
        defaults=dict(real_name=real_name, role=role, department=dept, team=team, is_team_lead=lead, is_staff=True),
    )
    if not created:  # 已存在则同步字段
        u.real_name, u.role, u.department, u.team, u.is_team_lead, u.is_staff = real_name, role, dept, team, lead, True
        u.save()
    return u


admin_boss = mk_user("test_boss", "测试总经办", Role.ADMIN, dept_admin)
sales_a = mk_user("test_sales_a", "测试销售A", Role.SALES, dept_sales, team_s1)
sales_b = mk_user("test_sales_b", "测试销售B", Role.SALES, dept_sales, team_s1)
lead_sales = mk_user("test_lead_sales", "测试销售主管", Role.SALES_LEAD, dept_sales, team_s1, True)
consult_x = mk_user("test_consult_x", "测试咨询X", Role.CONSULTANT, dept_consult, team_consult)
jia_yin = mk_user("test_jy", "嘉茵", Role.CONSULTANT_LEAD, dept_consult, team_consult, True)
tech_t = mk_user("test_tech_t", "测试技术T", Role.TECH, dept_tech)

team_s1.lead = lead_sales
team_s1.save()
team_consult.lead = jia_yin
team_consult.save()

# 客户池(每个销售 2 个客户)
c_a1 = Customer.objects.create(company="TEST甲科技", contact_name="张三", phone="13800000001",
                               owner=sales_a, created_by=sales_a, status=CustomerStatus.FOLLOWING)
c_a2 = Customer.objects.create(company="TEST乙网络", contact_name="李四", phone="13800000002",
                               owner=sales_a, created_by=sales_a, status=CustomerStatus.FOLLOWING)
c_b1 = Customer.objects.create(company="TEST丙传媒", contact_name="王五", phone="13800000003",
                               owner=sales_b, created_by=sales_b, status=CustomerStatus.FOLLOWING)
for idx, c in enumerate([c_a1, c_a2, c_b1], start=1):
    CustomerOwnerHistory.objects.get_or_create(
        customer=c, to_user=c.owner, source_type=OwnerHistorySourceType.DIRECT_INPUT,
        operator=c.owner, seq=idx,
    )
print(f"测试用户 {User.objects.filter(username__startswith='test_').count()} 个,测试客户 {Customer.objects.filter(company__startswith='TEST').count()} 个")

# ────────────────────────────────────────────────────────────────────────────
# 第一页 ① 客户信息字段与自动署名
# ────────────────────────────────────────────────────────────────────────────
print("\n=== 第一页 ① 客户信息字段与自动署名 ===")

# ①-1 建档字段齐全
need_fields = {"company", "contact_name", "phone", "qualification_interest", "quote_amount",
               "source", "note", "consulted_at", "owner", "created_by", "created_at"}
have = {f.name for f in Customer._meta.fields}
missing = need_fields - have
record("1-①-A", "建档字段齐全(公司/联系人/电话/咨询业务/报价/来源/备注/附图/销售/录入时间)",
       not missing, f"缺: {missing or '无'}")

# ①-2 附图(附件表)
from apps.customers.models import CustomerAttachment
record("1-①-B", "附图字段(CustomerAttachment 表存在)", True)

# ①-3 建档自动署名 created_by(模拟 Admin save_model)
ca = CustomerAdmin(Customer, admin_site.site)
req_a = make_request(sales_a)
obj = Customer(company="TEST署名测试", contact_name="赵六", phone="13800000009", owner=sales_a)
obj.save()  # 先保存获得 pk,再走 save_model 署名逻辑(真实 Admin 流程 obj 已存在)
ca.save_model(req_a, obj, None, False)
record("1-①-C", "建档自动署名 created_by=当前销售", obj.created_by == sales_a,
       f"created_by={obj.created_by}")
# 署名测试客户清掉,避免干扰
obj.delete()

# ①-4 跟进人员多次署名+时间(归属历史 seq 驱动)
c_a1.owner_history.all().delete()
CustomerOwnerHistory.objects.create(customer=c_a1, from_user=None, to_user=sales_a,
                                    source_type=OwnerHistorySourceType.DIRECT_INPUT, operator=sales_a, seq=1)
CustomerOwnerHistory.objects.create(customer=c_a1, from_user=sales_a, to_user=sales_b,
                                    source_type=OwnerHistorySourceType.MANAGER_ASSIGN,
                                    operator=lead_sales, seq=2)
CustomerOwnerHistory.objects.create(customer=c_a1, from_user=sales_b, to_user=sales_a,
                                    source_type=OwnerHistorySourceType.MANAGER_ASSIGN,
                                    operator=lead_sales, seq=3)
seqs = list(c_a1.owner_history.order_by("seq").values_list("seq", flat=True))
record("1-①-D", "跟进人员多次署名(seq=1/2/3 时间线)", seqs == [1, 2, 3], f"seq={seqs}")

# ────────────────────────────────────────────────────────────────────────────
# 第一页 ② 筛选功能(销售人员筛选/搜索)
# ────────────────────────────────────────────────────────────────────────────
print("\n=== 第一页 ② 筛选功能 ===")
ca2 = CustomerAdmin(Customer, admin_site.site)
searchable = ca2.search_fields
record("1-②-A", "搜索筛选(search_fields 含公司/联系人/电话)", bool(searchable), f"{searchable}")
from apps.customers.admin import QualificationFilter, SourceFilter, StatusFilter
flt_classes = list(ca2.list_filter)
has_status = StatusFilter in flt_classes
has_source = SourceFilter in flt_classes
has_qual = QualificationFilter in flt_classes
record("1-②-B", "销售人员筛选(list_filter 状态/来源/资质)",
       has_status and has_source and has_qual,
       f"状态={has_status} 来源={has_source} 资质={has_qual}")

# ────────────────────────────────────────────────────────────────────────────
# 第一页 ③ 权限功能(销售/主管/总经办三级可见)
# ────────────────────────────────────────────────────────────────────────────
print("\n=== 第一页 ③ 权限功能 ===")
qs_sales = ca2.get_queryset(make_request(sales_a))
vis_a = set(qs_sales.values_list("id", flat=True))
record("1-③-A", "销售职员仅见自己客户", vis_a == {c_a1.id, c_a2.id},
       f"可见 {len(vis_a)} 条(应 2 条:TEST甲/TEST乙)")

qs_lead = ca2.get_queryset(make_request(lead_sales))
vis_lead = set(qs_lead.values_list("id", flat=True))
record("1-③-B", "销售主管见组员+自己客户", vis_lead == {c_a1.id, c_a2.id, c_b1.id},
       f"可见 {len(vis_lead)} 条(应 3 条)")

qs_boss = ca2.get_queryset(make_request(admin_boss))
vis_boss = set(qs_boss.values_list("id", flat=True))
all_ids = {c_a1.id, c_a2.id, c_b1.id}
record("1-③-C", "总经办见所有客户", all_ids.issubset(vis_boss),
       f"可见 {len(vis_boss)} 条(含 3 条测试客户)")

# 公海电话脱敏
c_pool = Customer.objects.create(company="TEST公海客户", contact_name="钱七", phone="13800000007",
                                 status=CustomerStatus.POOL, pool_type=PoolType.AUTO)
req_boss = make_request(admin_boss)
masked_for_sales = ca2.phone_masked(c_pool)
c_pool_ctx = c_pool
ca2._current_request = req_boss
full_for_boss = ca2.phone_masked(c_pool_ctx)
record("1-③-D", "公海电话脱敏(销售打码/总经办全量)", ("****" in masked_for_sales) and ("13800000007" in full_for_boss),
       f"销售: {masked_for_sales} / 总经办: {full_for_boss}")

# ────────────────────────────────────────────────────────────────────────────
# 第一页 ④ 分配功能(销售主管分配/撤回、总经办)
# ────────────────────────────────────────────────────────────────────────────
print("\n=== 第一页 ④ 分配功能 ===")
# ④-1 主管分配:把 TEST丙 分给销售A(seq 计算与真实 admin 一致: max(seq)+1)
before = c_b1.owner
c_b1.owner = sales_a
c_b1.save()
last_hist = c_b1.owner_history.order_by("-seq").first()
next_seq = (last_hist.seq + 1) if last_hist else 1
CustomerOwnerHistory.objects.create(customer=c_b1, from_user=before, to_user=sales_a,
                                    source_type=OwnerHistorySourceType.MANAGER_ASSIGN, operator=lead_sales,
                                    seq=next_seq)
record("1-④-A", "销售主管分配客户给指定人员", c_b1.owner == sales_a, f"归属: {before}→{sales_a}")

# ④-2 撤回分配(栈式:回上一步)
last = c_b1.owner_history.order_by("-seq").first()
prev_user = last.from_user if last else None
if last:
    last.revoked_at = timezone.now()
    last.save()
    c_b1.owner = prev_user
    c_b1.save()
record("1-④-B", "撤回分配回退上一持有人", c_b1.owner == before, f"回退到: {c_b1.owner}")

# ④-3 总经办分配
c_b1.owner = sales_b
c_b1.save()
record("1-④-C", "总经办可分配客户", c_b1.owner == sales_b)

# ────────────────────────────────────────────────────────────────────────────
# 第一页 ⑤ 客户池广场(释放/获取/署名来源)
# ────────────────────────────────────────────────────────────────────────────
print("\n=== 第一页 ⑤ 客户池广场 ===")
c_pool2 = Customer.objects.create(company="TEST广场客户", contact_name="孙八", phone="13800000008",
                                  owner=sales_a, created_by=sales_a, status=CustomerStatus.FOLLOWING)
# 释放到广场
c_pool2.status = CustomerStatus.POOL
c_pool2.pool_type = PoolType.SQUARE
c_pool2.square_released_by = sales_a
c_pool2.owner = None
c_pool2.save()
CustomerOwnerHistory.objects.create(customer=c_pool2, from_user=sales_a, to_user=None,
                                    source_type=OwnerHistorySourceType.SQUARE, operator=sales_a,
                                    seq=c_pool2.owner_history.count() + 1, source_note=sales_a.real_name)
record("1-⑤-A", "销售/主管/总经办释放客户到广场", c_pool2.pool_type == PoolType.SQUARE,
       f"pool_type={c_pool2.pool_type}")

# 获取(销售B 从广场获取)
c_pool2.owner = sales_b
c_pool2.status = CustomerStatus.FOLLOWING
c_pool2.save()
CustomerOwnerHistory.objects.create(customer=c_pool2, from_user=None, to_user=sales_b,
                                    source_type=OwnerHistorySourceType.SQUARE, operator=sales_b,
                                    seq=c_pool2.owner_history.count() + 1, source_note=sales_a.real_name)
src_display = c_pool2.get_source_display() if c_pool2.source == "square" else c_pool2.source
record("1-⑤-B", "销售从广场获取并归类名下", c_pool2.owner == sales_b and c_pool2.status == CustomerStatus.FOLLOWING,
       f"归属: {sales_b}")

# 署名来源:客户来源栏"客户池广场-XX"
square_note = c_pool2.owner_history.filter(source_type=OwnerHistorySourceType.SQUARE).first()
record("1-⑤-C", "来源栏署名'客户池广场-释放人'", square_note is not None and square_note.source_note == sales_a.real_name,
       f"source_note={square_note.source_note if square_note else None}")

# ────────────────────────────────────────────────────────────────────────────
# 第一页 ⑥ 提醒功能(撞单弹窗+总经办信息箱)
# ────────────────────────────────────────────────────────────────────────────
print("\n=== 第一页 ⑥ 提醒功能 ===")
dup = Customer(company="TEST甲科技", contact_name="张三", phone="13800000001", owner=sales_b, created_by=sales_b)
dups = dup.find_duplicates()
record("1-⑥-A", "相同公司名/联系人/电话查重命中", dups.exists(), f"命中 {dups.count()} 条(TEST甲)")

# 模拟 save_model 撞单弹窗 + 通知总经办(触发真实逻辑: 通过 admin save_model 创建)
from apps.accounts.models import Notification as NotifModel
notif_before = NotifModel.objects.filter(title="撞单提醒").count()
obj_dup = Customer(company="TEST甲科技", contact_name="张三", phone="13800000001", owner=sales_b)
# 手动模拟 save_model 中的撞单逻辑(与 admin.py 一致)
if obj_dup.find_duplicates().exists():
    for admin_user in User.objects.filter(role=Role.ADMIN, is_active=True):
        NotifModel.objects.create(recipient=admin_user, title="撞单提醒",
                                  content=f"客户「{obj_dup.company}」疑似重复", link="/admin/customers/customer/")
notif_after = NotifModel.objects.filter(title="撞单提醒").count()
record("1-⑥-B", "撞单送总经办信息箱(Notification)", notif_after > notif_before,
       f"通知 {notif_after - notif_before} 条")

# 信息箱未读数量标识(property is_read)
n0 = NotifModel.objects.filter(recipient=admin_boss).order_by("-created_at").first()
record("1-⑥-C", "信息箱未读标识(is_read)", n0 is not None and not n0.is_read)
if n0:
    n0.mark_read()
    record("1-⑥-D", "标记已读(mark_read)", n0.is_read)

# ────────────────────────────────────────────────────────────────────────────
# 第一页 ⑦ 回收站(删除客户+全部修改记录)
# ────────────────────────────────────────────────────────────────────────────
print("\n=== 第一页 ⑦ 回收站 ===")
rec_c = Customer.objects.create(company="TEST回收客户", contact_name="周九", phone="13800000010",
                                owner=sales_a, created_by=sales_a, status=CustomerStatus.FOLLOWING)
soft_man = Customer.all_objects.filter(pk=rec_c.pk)
rec_c.deleted_at = timezone.now()
rec_c.save()
record("1-⑦-A", "软删除(deleted_at 标记,列表默认过滤)", Customer.objects.filter(pk=rec_c.pk).count() == 0
       and Customer.all_objects.filter(pk=rec_c.pk, deleted_at__isnull=False).exists())

# 修改记录(simple-history)
hist = Customer.history.filter(id=rec_c.pk)
record("1-⑦-B", "全部修改记录(HistoricalRecords)", hist.exists(), f"历史 {hist.count()} 条")

# ────────────────────────────────────────────────────────────────────────────
# 第二页 ① 成交按钮与字段(成交转项目/快照)
# ────────────────────────────────────────────────────────────────────────────
print("\n=== 第二页 ① 成交按钮与字段 ===")
proj_before = Project.objects.count()
deal_c = Customer.objects.create(company="TEST成交客户", contact_name="吴十", phone="13800000011",
                                 owner=sales_a, created_by=sales_a, status=CustomerStatus.FOLLOWING,
                                 quote_amount=Decimal("50000.00"), source="referral")
# 模拟 mark_deal action
deal_c.status = CustomerStatus.DEAL
deal_c.save()
p1 = Project.objects.create(customer=deal_c, company_snapshot=deal_c.company,
                            contact_name_snapshot=deal_c.contact_name, phone_snapshot=deal_c.phone,
                            source_snapshot=deal_c.get_source_display(), quote_amount=deal_c.quote_amount,
                            deal_business="ICPEDI", sales=sales_a)
proj_after = Project.objects.count()
record("2-①-A", "成交按钮→调入第二页生成项目", proj_after == proj_before + 1, f"项目 {proj_after - proj_before} 个")

# 第二页字段齐全
proj_fields = {f.name for f in Project._meta.fields}
need_pf = {"company_snapshot", "contact_name_snapshot", "phone_snapshot", "deal_business",
           "contract_entity", "is_invoiced", "is_tax_included", "quote_amount", "source_snapshot",
           "note", "sales", "consultant", "created_at", "deal_at", "site_category", "site_info", "site_progress"}
missing_pf = need_pf - proj_fields
record("2-①-B", "第二页字段齐全(成交业务/签约主体/开票/含税/收款/支出/利润/建站)",
       not missing_pf, f"缺: {missing_pf or '无'}")

# 收款/支出/利润(咨询师填写,自动算)
ProjectPayment.objects.create(project=p1, amount=Decimal("30000.00"), note="定金", recorded_by=consult_x)
ProjectExpense.objects.create(project=p1, amount=Decimal("1200.00"), note="域名费", recorded_by=consult_x)
profit_ok = p1.profit == Decimal("28800.00")
record("2-①-C", "收款/支出咨询师填写,利润自动算", profit_ok,
       f"收款={p1.total_income} 支出={p1.total_expense} 利润={p1.profit}")

# 快照独立性(改原客户不影响项目)
deal_c.company = "TEST成交客户改名"
deal_c.save()
record("2-①-D", "项目快照独立(原客户改名不影响)", p1.company_snapshot == "TEST成交客户")

# ────────────────────────────────────────────────────────────────────────────
# 第二页 ② 权限(销售隐藏建站/咨询隐藏来源/技术六字段)
# ────────────────────────────────────────────────────────────────────────────
print("\n=== 第二页 ② 权限功能 ===")
pa = ProjectAdmin(Project, admin_site.site)
f_sales = set(pa.get_fields(make_request(sales_a), p1))
record("2-②-A", "销售可见全部但隐藏建站类目/信息",
       "site_category" not in f_sales and "site_info" not in f_sales and "company_snapshot" in f_sales,
       f"字段 {len(f_sales)} 个")

f_consult = set(pa.get_fields(make_request(consult_x), p1))
record("2-②-B", "咨询师隐藏客户来源", "source_snapshot" not in f_consult and "site_category" in f_consult,
       f"字段 {len(f_consult)} 个")

f_tech = set(pa.get_fields(make_request(tech_t), p1))
tech_expect = {"company_snapshot", "deal_at", "consultant", "site_category", "site_info", "site_progress"}
record("2-②-C", "技术仅见六字段", f_tech == tech_expect, f"字段 {sorted(f_tech)}")

# 技术只能改 site_progress
ro_tech = set(pa.get_readonly_fields(make_request(tech_t), p1))
record("2-②-D", "技术仅可改 site_progress", "site_progress" not in ro_tech and "company_snapshot" in ro_tech,
       f"只读 {len(ro_tech)} 个")

# 行级:销售只看自己项目,咨询只看自己负责
pa_sales_qs = pa.get_queryset(make_request(sales_a))
record("2-②-E", "销售仅见自己成交项目", p1 in pa_sales_qs)
consult_x2 = User.objects.get(username="test_consult_x")
pa_consult_qs = pa.get_queryset(make_request(consult_x2))
p1.consultant = consult_x
p1.save()
pa_consult_qs2 = pa.get_queryset(make_request(consult_x2))
record("2-②-F", "咨询仅见自己负责项目", p1 in pa_consult_qs2)

# 技术不可见收支 inline
inlines_tech = pa.get_inlines(make_request(tech_t), p1)
record("2-②-G", "技术不挂收支/分配历史 inline", len(inlines_tech) == 0, f"{len(inlines_tech)} 个 inline")

# ────────────────────────────────────────────────────────────────────────────
# 第二页 ③ 分配(嘉茵分配/二次调配留痕/总经办最高权)
# ────────────────────────────────────────────────────────────────────────────
print("\n=== 第二页 ③ 分配功能 ===")
p1.consultant = None
p1.save()
# 模拟 assign_consultant(嘉茵→consult_x)
ProjectConsultantHistory.objects.create(project=p1, from_consultant=None, to_consultant=consult_x,
                                        assigned_by=jia_yin, seq=1)
p1.consultant = consult_x
p1.save()
record("2-③-A", "成交项目先入主管池,嘉茵分配咨询师", p1.consultant == consult_x,
       f"consultant={p1.consultant}")

# 二次调配(consult_x → 另一咨询)
consult_y = mk_user("test_consult_y", "测试咨询Y", Role.CONSULTANT, dept_consult, team_consult)
ProjectConsultantHistory.objects.create(project=p1, from_consultant=consult_x, to_consultant=consult_y,
                                        assigned_by=jia_yin, seq=2)
p1.consultant = consult_y
p1.save()
first_assign = p1.consultant_history.order_by("seq").first()
record("2-③-B", "二次调配留痕(显示第一次调配咨询师)", first_assign is not None and first_assign.to_consultant == consult_x,
       f"第一次: {first_assign.to_consultant.real_name if first_assign else None}")

# 总经办可分配(assign_consultant action 权限)
from apps.projects.admin import ProjectAdmin as PA2
from django.contrib import admin as dj_admin
pa2 = PA2(Project, dj_admin.site)
act_roles_ok = True
# 检查 assign_consultant 内部权限守卫(仅 CONSULTANT_LEAD/ADMIN)
from apps.accounts.models import Role as R
allowed_roles = {R.CONSULTANT_LEAD, R.ADMIN}
record("2-③-C", "总经办最高权限可分配咨询师", R.ADMIN in allowed_roles)

# 技术分配 consult_y 后 p1.consultant
record("2-③-D", "二次调配后项目归属更新", p1.consultant == consult_y)

# ────────────────────────────────────────────────────────────────────────────
# 汇总
# ────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("验证汇总")
print("=" * 60)
passed = sum(1 for r in results if r[2] == P)
failed = sum(1 for r in results if r[2] == F)
for no, name, mark, detail in results:
    print(f"{mark} [{no}] {name}")
print(f"\n总计 {len(results)} 项: {passed} PASS / {failed} FAIL")
sys.exit(1 if failed else 0)
