"""成交项目模块回归测试——覆盖本轮修复的细则条款."""
from decimal import Decimal

from django.contrib import admin as dj_admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from apps.accounts.models import Role
from apps.customers.models import Customer, CustomerStatus, OwnerHistorySourceType, CustomerOwnerHistory
from apps.projects.admin import ProjectAdmin
from apps.projects.models import Project, ProjectConsultantHistory, ProjectExpense, ProjectPayment, SiteProgress

User = get_user_model()

PWD = "x"  # 测试口令常量,避免被密钥扫描器误判


def make_request(user, data=None, method="post"):
    factory = RequestFactory()
    req = getattr(factory, method)("/admin/projects/project/", data or {})
    req.user = user
    req.session = "test-session"
    req._messages = FallbackStorage(req)
    return req


class ProjectBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="p_admin", password=PWD, real_name="总办", role=Role.ADMIN,
            is_staff=True, is_superuser=True,
        )
        self.sales = User.objects.create_user(
            username="p_sales", password=PWD, real_name="销售甲", role=Role.SALES, is_staff=True,
        )
        self.consultant = User.objects.create_user(
            username="p_consult", password=PWD, real_name="咨询师乙", role=Role.CONSULTANT, is_staff=True,
        )
        self.jia_yin = User.objects.create_user(
            username="p_jiayin", password=PWD, real_name="嘉茵", role=Role.CONSULTANT_LEAD, is_staff=True,
        )
        self.tech = User.objects.create_user(
            username="p_tech", password=PWD, real_name="技术丙", role=Role.TECH, is_staff=True,
        )
        self.customer = Customer.objects.create(
            company="项目客户", contact_name="王五", phone="13800000002",
            status=CustomerStatus.FOLLOWING, owner=self.sales, created_by=self.sales,
        )
        CustomerOwnerHistory.objects.create(
            customer=self.customer, from_user=None, to_user=self.sales,
            source_type=OwnerHistorySourceType.DIRECT_INPUT, operator=self.sales, seq=1,
        )
        self.project_admin = ProjectAdmin(Project, dj_admin.site)

    def make_project(self, **kw):
        defaults = dict(
            customer=self.customer, company_snapshot="项目客户", contact_name_snapshot="王五",
            phone_snapshot="13800000002", sales=self.sales,
        )
        defaults.update(kw)
        return Project.objects.create(**defaults)


class MarkDealTests(ProjectBase):
    def test_mark_deal_creates_project_idempotent(self):
        """成交:自动建项目快照,重复执行不重复建."""
        from apps.customers.admin import CustomerAdmin
        from apps.customers.models import Customer as C
        ca = CustomerAdmin(C, dj_admin.site)
        ca.mark_deal(make_request(self.sales), C.objects.filter(pk=self.customer.pk))
        self.assertEqual(Project.objects.filter(customer=self.customer).count(), 1)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.status, CustomerStatus.DEAL)
        # 再次执行:DEAL 客户不在候选内,项目仍只有 1 个
        ca.mark_deal(make_request(self.admin), C.objects.filter(pk=self.customer.pk))
        self.assertEqual(Project.objects.filter(customer=self.customer).count(), 1)

    def test_mark_deal_rejected_for_non_sales_roles(self):
        from apps.customers.admin import CustomerAdmin
        from apps.customers.models import Customer as C
        ca = CustomerAdmin(C, dj_admin.site)
        ca.mark_deal(make_request(self.tech), C.objects.filter(pk=self.customer.pk))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.status, CustomerStatus.FOLLOWING)
        self.assertEqual(Project.objects.count(), 0)


class RoleFieldVisibilityTests(ProjectBase):
    def test_tech_list_columns_restricted(self):
        """细则第二页:技术仅六字段——列表页不得出现销售/成交业务/利润列."""
        req = make_request(self.tech, method="get")
        cols = self.project_admin.get_list_display(req)
        self.assertNotIn("sales", cols)
        self.assertNotIn("deal_business", cols)
        self.assertNotIn("profit_display", cols)
        self.assertIn("company_snapshot", cols)
        self.assertIn("site_progress", cols)
        # 技术的检索字段仅剩公司名（不能按联系人/电话搜）
        self.assertEqual(self.project_admin.get_search_fields(req), ("company_snapshot",))

    def test_money_fields_shown_except_tech(self):
        """修复:收款/支出/利润汇总此前未进 get_fields,详情页从不展示."""
        req = make_request(self.consultant, method="get")
        fields = self.project_admin.get_fields(req, obj=self.make_project())
        for f in ("profit_display", "total_income_display", "total_expense_display"):
            self.assertIn(f, fields)
        req_tech = make_request(self.tech, method="get")
        tech_fields = self.project_admin.get_fields(req_tech, obj=self.make_project())
        self.assertNotIn("profit_display", tech_fields)
        self.assertNotIn("source_snapshot", tech_fields)

    def test_consultant_hides_source(self):
        req = make_request(self.consultant, method="get")
        fields = self.project_admin.get_fields(req, obj=self.make_project())
        self.assertNotIn("source_snapshot", fields)
        # 咨询主管嘉茵全字段可见
        req_lead = make_request(self.jia_yin, method="get")
        lead_fields = self.project_admin.get_fields(req_lead, obj=self.make_project())
        self.assertIn("source_snapshot", lead_fields)


class ProfitTests(ProjectBase):
    def test_profit_annotation_no_double_count(self):
        """分次收支:预聚合注解与属性口径一致,多行收款/支出不互相放大."""
        p = self.make_project()
        ProjectPayment.objects.create(project=p, amount=100, recorded_by=self.consultant)
        ProjectPayment.objects.create(project=p, amount=50, recorded_by=self.consultant)
        ProjectExpense.objects.create(project=p, amount=30, recorded_by=self.consultant)
        ProjectExpense.objects.create(project=p, amount=20, recorded_by=self.consultant)
        qs = self.project_admin.get_queryset(make_request(self.admin, method="get"))
        annotated = qs.get(pk=p.pk)
        self.assertEqual(annotated.income_annotated, Decimal("150"))
        self.assertEqual(annotated.expense_annotated, Decimal("50"))
        self.assertEqual(self.project_admin.profit_display(annotated), Decimal("100"))
        p.refresh_from_db()
        self.assertEqual(p.profit, Decimal("100"))


class AssignConsultantTests(ProjectBase):
    def test_assign_and_reassign_keeps_history(self):
        """嘉茵分配/二次调配:历史保留第一次分配记录."""
        p = self.make_project()
        req = make_request(self.jia_yin, {"apply": "1", "new_consultant": str(self.consultant.pk)})
        self.project_admin.assign_consultant(req, Project.objects.filter(pk=p.pk))
        p.refresh_from_db()
        self.assertEqual(p.consultant, self.consultant)
        # 二次调配给新咨询师
        other = User.objects.create_user(
            username="p_consult2", password=PWD, real_name="咨询师丁", role=Role.CONSULTANT, is_staff=True,
        )
        req2 = make_request(self.jia_yin, {"apply": "1", "new_consultant": str(other.pk)})
        self.project_admin.assign_consultant(req2, Project.objects.filter(pk=p.pk))
        p.refresh_from_db()
        self.assertEqual(p.consultant, other)
        first = p.consultant_history.order_by("seq").first()
        self.assertEqual(first.to_consultant, self.consultant)  # 第一次记录保留
        self.assertEqual(p.consultant_history.count(), 2)

    def test_assign_rejects_non_consultant_target(self):
        p = self.make_project()
        req = make_request(self.jia_yin, {"apply": "1", "new_consultant": str(self.tech.pk)})
        self.project_admin.assign_consultant(req, Project.objects.filter(pk=p.pk))
        p.refresh_from_db()
        self.assertIsNone(p.consultant)
        self.assertEqual(ProjectConsultantHistory.objects.count(), 0)

    def test_assign_rejected_for_plain_consultant(self):
        p = self.make_project()
        req = make_request(self.consultant, {"apply": "1", "new_consultant": str(self.consultant.pk)})
        self.project_admin.assign_consultant(req, Project.objects.filter(pk=p.pk))
        p.refresh_from_db()
        self.assertIsNone(p.consultant)

    def test_tech_save_model_only_updates_progress(self):
        """技术提交表单:只落 site_progress,其余字段不被覆盖."""
        p = self.make_project(site_category="官网", site_info="php建站", deal_business="ICP", tech_assigned=self.tech)
        req = make_request(self.tech)
        p.site_progress = SiteProgress.DEPLOYED
        p.deal_business = "被篡改"
        self.project_admin.save_model(req, p, form=None, change=True)
        p.refresh_from_db()
        self.assertEqual(p.site_progress, SiteProgress.DEPLOYED)
        self.assertEqual(p.deal_business, "ICP")
