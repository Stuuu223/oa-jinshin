"""客户模块回归测试——覆盖本轮修复的细则条款."""
from datetime import timedelta

from django.contrib import admin as dj_admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.customers.admin import CustomerAdmin, RecycledCustomerAdmin
from apps.customers.models import (
    Customer, CustomerOwnerHistory, CustomerStatus, OwnerHistorySourceType, PoolType,
    RecycledCustomer, Source,
)

User = get_user_model()

PWD = "x"  # 测试口令常量,避免被密钥扫描器误判


def make_request(user, data=None, method="post"):
    factory = RequestFactory()
    req = getattr(factory, method)("/admin/customers/customer/", data or {})
    req.user = user
    req.session = "test-session"  # FallbackStorage 的占位
    req._messages = FallbackStorage(req)
    return req


class BaseData(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="t_admin", password=PWD, real_name="总办", role=Role.ADMIN,
            is_staff=True, is_superuser=True,
        )
        self.sales1 = User.objects.create_user(
            username="t_sales1", password=PWD, real_name="张三", role=Role.SALES, is_staff=True,
        )
        self.sales2 = User.objects.create_user(
            username="t_sales2", password=PWD, real_name="李四", role=Role.SALES, is_staff=True,
        )
        self.tech = User.objects.create_user(
            username="t_tech", password=PWD, real_name="王工", role=Role.TECH, is_staff=True,
        )
        self.customer_admin = CustomerAdmin(Customer, dj_admin.site)
        self.recycled_admin = RecycledCustomerAdmin(RecycledCustomer, dj_admin.site)

    def make_customer(self, **kw):
        defaults = dict(
            company="测试公司A", contact_name="联系人", phone="13800000001",
            status=CustomerStatus.FOLLOWING, owner=self.sales1, created_by=self.sales1,
        )
        defaults.update(kw)
        c = Customer.objects.create(**defaults)
        CustomerOwnerHistory.objects.create(
            customer=c, from_user=None, to_user=self.sales1,
            source_type=OwnerHistorySourceType.DIRECT_INPUT, operator=self.sales1, seq=1,
        )
        return c


class SaveModelTests(BaseData):
    def test_add_customer_creates_history_and_does_not_crash(self):
        """新增客户:先落库再写归属历史（旧代码顺序反了会 500）."""
        c = Customer(company="新增客户", contact_name="张", phone="13911112222", owner=self.sales1)
        self.customer_admin.save_model(make_request(self.sales1), c, form=None, change=False)
        c.refresh_from_db()
        self.assertEqual(c.created_by, self.sales1)
        self.assertEqual(c.owner_history.count(), 1)
        self.assertEqual(c.owner_history.first().to_user, self.sales1)

    def test_duplicate_flags_and_notifies_admins(self):
        """撞单:录入重复信息做标识 + 送总经办信息箱."""
        self.make_customer(company="重复公司", phone="13800000001")
        c2 = Customer(company="重复公司", contact_name="李", phone="13700000000", owner=self.sales2)
        self.customer_admin.save_model(make_request(self.sales2), c2, form=None, change=False)
        c2.refresh_from_db()
        self.assertIsNotNone(c2.duplicate_flagged_at)
        self.assertTrue(
            self.admin.notifications.filter(title="撞单提醒", content__contains="重复公司").exists()
        )

    def test_edit_marks_system_fields_readonly(self):
        """编辑态:归属/状态字段只读,防手改绕过署名与历史."""
        c = self.make_customer()
        req = make_request(self.admin, method="get")
        readonly = self.customer_admin.get_readonly_fields(req, obj=c)
        for f in ("owner", "status", "pool_type", "last_follow_at", "lost_reason"):
            self.assertIn(f, readonly)
        # 新建态 owner 可选
        add_readonly = self.customer_admin.get_readonly_fields(req, obj=None)
        self.assertNotIn("owner", add_readonly)


class SquareFlowTests(BaseData):
    def test_release_to_square_keeps_source_clean(self):
        """释放到广场:source 走枚举 square,署名存 square_released_by,不再污染字段."""
        c = self.make_customer()
        req = make_request(self.sales1, {"apply": "1", "reason": "暂无意向"})
        self.customer_admin.release_to_square(req, Customer.objects.filter(pk=c.pk))
        c.refresh_from_db()
        self.assertEqual(c.status, CustomerStatus.POOL)
        self.assertEqual(c.pool_type, PoolType.SQUARE)
        self.assertEqual(c.source, Source.SQUARE)
        self.assertEqual(c.square_released_by, self.sales1)
        self.assertEqual(c.source_label, "客户池广场-张三")
        self.assertTrue(Customer.objects.filter(source="square").exists())

    def test_claim_from_pool_signature_flow(self):
        """获取广场客户:归属到获取人,来源栏保留'客户池广场-释放人'署名."""
        c = self.make_customer()
        req = make_request(self.sales1, {"apply": "1", "reason": "暂无意向"})
        self.customer_admin.release_to_square(req, Customer.objects.filter(pk=c.pk))
        req2 = make_request(self.sales2)
        self.customer_admin.claim_from_pool(req2, Customer.objects.filter(pk=c.pk))
        c.refresh_from_db()
        self.assertEqual(c.owner, self.sales2)
        self.assertEqual(c.status, CustomerStatus.FOLLOWING)
        self.assertEqual(c.source_label, "客户池广场-张三")  # 署名保留
        last = c.owner_history.order_by("-seq").first()
        self.assertEqual(last.source_type, OwnerHistorySourceType.SQUARE)
        self.assertEqual(last.source_note, "张三")
        self.assertEqual(last.operator, self.sales2)


class AssignAndRevokeTests(BaseData):
    def test_assign_owned_customer_records_from_user_and_notifies(self):
        """细则第一页·四:分配管辖内客户（非公海也行）,历史记上一持有人,并通知目标."""
        c = self.make_customer()  # FOLLOWING, owner=sales1
        req = make_request(self.admin, {
            "apply": "1", "new_owner": str(self.sales2.pk), "reason": "交接",
        })
        self.customer_admin.assign_pool(req, Customer.objects.filter(pk=c.pk))
        c.refresh_from_db()
        self.assertEqual(c.owner, self.sales2)
        last = c.owner_history.order_by("-seq").first()
        self.assertEqual(last.from_user, self.sales1)
        self.assertEqual(last.to_user, self.sales2)
        self.assertTrue(self.sales2.notifications.filter(title="客户分配通知").exists())

    def test_assign_rejects_invalid_target(self):
        c = self.make_customer()
        req = make_request(self.admin, {
            "apply": "1", "new_owner": str(self.tech.pk), "reason": "越权目标",
        })
        self.customer_admin.assign_pool(req, Customer.objects.filter(pk=c.pk))
        c.refresh_from_db()
        self.assertEqual(c.owner, self.sales1)  # 未变
        self.assertFalse(self.tech.notifications.filter(title="客户分配通知").exists())

    def test_revoke_restores_previous_owner(self):
        """撤销分配 = 弹栈,回退到上一持有人."""
        c = self.make_customer()
        req = make_request(self.admin, {
            "apply": "1", "new_owner": str(self.sales2.pk), "reason": "交接",
        })
        self.customer_admin.assign_pool(req, Customer.objects.filter(pk=c.pk))
        self.customer_admin.revoke_assignment(
            make_request(self.admin), Customer.objects.filter(pk=c.pk)
        )
        c.refresh_from_db()
        self.assertEqual(c.owner, self.sales1)
        self.assertEqual(c.status, CustomerStatus.FOLLOWING)


class RecycleBinTests(BaseData):
    def test_soft_delete_hides_and_restore(self):
        """回收站:删除进软删,回收站可见,可恢复."""
        c = self.make_customer()
        self.customer_admin.soft_delete(
            make_request(self.sales1), Customer.objects.filter(pk=c.pk)
        )
        self.assertFalse(Customer.objects.filter(pk=c.pk).exists())
        self.assertTrue(RecycledCustomer.objects.filter(pk=c.pk, deleted_at__isnull=False).exists())
        # 回收站 admin 只对总经办可见
        req = make_request(self.admin, method="get")
        self.assertTrue(self.recycled_admin.has_view_permission(req))
        req_sales = make_request(self.sales1, method="get")
        self.assertFalse(self.recycled_admin.has_view_permission(req_sales))
        # 恢复
        self.recycled_admin.restore(
            make_request(self.admin), RecycledCustomer.objects.filter(pk=c.pk)
        )
        self.assertTrue(Customer.objects.filter(pk=c.pk).exists())


class RoleVisibilityTests(BaseData):
    def test_first_page_roles_queryset(self):
        """细则第一页·三:销售看自己,主管看组员+自己,总经办看全部;咨询/技术不可见."""
        self.make_customer(company="张三的客户")
        self.make_customer(company="李四的客户", owner=self.sales2, created_by=self.sales2)
        qs_sales = self.customer_admin.get_queryset(make_request(self.sales1, method="get"))
        self.assertEqual(qs_sales.count(), 1)
        qs_tech = self.customer_admin.get_queryset(make_request(self.tech, method="get"))
        self.assertEqual(qs_tech.count(), 0)
        qs_admin = self.customer_admin.get_queryset(make_request(self.admin, method="get"))
        self.assertEqual(qs_admin.count(), 2)

    def test_actions_filtered_by_role(self):
        """技术/财务等非销售序列拿不到任何客户动作,默认硬删动作不暴露."""
        actions = self.customer_admin.get_actions(make_request(self.tech, method="get"))
        self.assertEqual(len(actions), 0)
        actions_sales = self.customer_admin.get_actions(make_request(self.sales1, method="get"))
        self.assertIn("release_to_square", actions_sales)
        self.assertNotIn("assign_pool", actions_sales)
        self.assertNotIn("delete_selected", actions_sales)


class DupCheckViewTests(BaseData):
    def test_check_duplicates_json(self):
        """录入前预检接口:命中重复返回公司名与归属."""
        self.make_customer(company="星辰科技")
        req = make_request(self.sales2, {"company": "星辰科技", "contact": "", "phone": ""}, method="get")
        resp = self.customer_admin.check_duplicates_view(req)
        import json
        data = json.loads(resp.content)
        self.assertEqual(len(data["duplicates"]), 1)
        self.assertEqual(data["duplicates"][0]["company"], "星辰科技")
        self.assertEqual(data["duplicates"][0]["owner"], "张三")


class StalePoolCommandTests(BaseData):
    def test_stale_customer_auto_pool(self):
        """30天未跟进自动掉公海:状态/类型/归属历史三件套齐落."""
        c = self.make_customer(last_follow_at=timezone.now() - timedelta(days=40))
        call_command("release_stale_customers")
        c.refresh_from_db()
        self.assertEqual(c.status, CustomerStatus.POOL)
        self.assertEqual(c.pool_type, PoolType.AUTO)
        last = c.owner_history.order_by("-seq").first()
        self.assertEqual(last.source_type, OwnerHistorySourceType.AUTO_POOL)


class FollowUpTimeTests(BaseData):
    def test_followup_time_default_and_backdatable(self):
        """跟进时间:默认当前时刻,也可手动补录过去的时间(修复 auto_now_add 只读)."""
        from apps.customers.models import FollowUp
        c = self.make_customer()
        f1 = FollowUp.objects.create(customer=c, user=self.sales1, content="电话沟通")
        self.assertIsNotNone(f1.created_at)
        past = timezone.now() - timedelta(days=3)
        f2 = FollowUp.objects.create(
            customer=c, user=self.sales1, content="补录上周微信", created_at=past,
        )
        f2.refresh_from_db()
        self.assertEqual(f2.created_at, past)
        # 客户最近跟进时间联动 = 最新一条(而非最后写入的一条)
        Customer.objects.filter(pk=c.pk).update(
            last_follow_at=c.follow_ups.order_by("-created_at").first().created_at
        )
        c.refresh_from_db()
        self.assertEqual(c.last_follow_at, f1.created_at)
