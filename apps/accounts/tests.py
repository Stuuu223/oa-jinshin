"""账号模块回归测试——信息箱可读/可清零、登录跳转."""
from django.contrib import admin as dj_admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import Client, RequestFactory, TestCase

from apps.accounts.admin import NotificationAdmin
from apps.accounts.models import Notification, Role

User = get_user_model()

PWD = "x"  # 测试口令常量,避免被密钥扫描器误判


def make_request(user, data=None, method="post"):
    factory = RequestFactory()
    req = getattr(factory, method)("/admin/accounts/notification/", data or {})
    req.user = user
    req.session = "test-session"
    req._messages = FallbackStorage(req)
    return req


class NotificationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="n_admin", password=PWD, real_name="总办", role=Role.ADMIN,
            is_staff=True, is_superuser=True,
        )
        self.sales = User.objects.create_user(
            username="n_sales", password=PWD, real_name="销售", role=Role.SALES, is_staff=True,
        )
        self.notification_admin = NotificationAdmin(Notification, dj_admin.site)
        for i in range(3):
            Notification.objects.create(recipient=self.admin, title=f"撞单提醒{i}", content="测试")

    def test_unread_can_be_cleared(self):
        """修复:此前信息箱全只读,未读数只增不减（死锁）."""
        self.assertEqual(
            Notification.objects.filter(recipient=self.admin, read_at__isnull=True).count(), 3
        )
        first_two = list(Notification.objects.filter(read_at__isnull=True).values_list("pk", flat=True)[:2])
        self.notification_admin.mark_read(
            make_request(self.admin), Notification.objects.filter(pk__in=first_two)
        )
        self.assertEqual(
            Notification.objects.filter(recipient=self.admin, read_at__isnull=True).count(), 1
        )
        self.notification_admin.mark_all_read(
            make_request(self.admin), Notification.objects.none()
        )
        self.assertEqual(
            Notification.objects.filter(recipient=self.admin, read_at__isnull=True).count(), 0
        )

    def test_queryset_scoped_to_recipient(self):
        """普通员工只看自己的通知,总经办可见全部."""
        Notification.objects.create(recipient=self.sales, title="分配通知", content="测试")
        qs_sales = self.notification_admin.get_queryset(make_request(self.sales, method="get"))
        self.assertEqual(qs_sales.count(), 1)
        self.assertEqual(qs_sales.first().title, "分配通知")
        qs_admin = self.notification_admin.get_queryset(make_request(self.admin, method="get"))
        self.assertEqual(qs_admin.count(), 4)

    def test_staff_role_has_admin_access(self):
        """修复:员工无 Django 权限表记录也能按角色进入对应模块（此前一律 403）."""
        req = make_request(self.sales, method="get")
        self.assertTrue(self.notification_admin.has_view_permission(req))
        from apps.customers.admin import CustomerAdmin
        from apps.customers.models import Customer
        customer_admin = CustomerAdmin(Customer, dj_admin.site)
        self.assertTrue(customer_admin.has_view_permission(req))


class DashboardRedirectTests(TestCase):
    def test_anonymous_redirected_to_login(self):
        """修复:未登录访问 dashboard 直接渲染登录模板(无错误提示/无回跳)."""
        resp = Client().get("/admin/dashboard/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])
        self.assertIn("next", resp["Location"])


class NotifyServiceTests(TestCase):
    """通知服务 notify():幂等防刷屏/批量/失败隔离/字段落库(2026-08-29 升级)."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="t_admin", password=PWD, real_name="总办", role=Role.ADMIN,
            is_staff=True, is_superuser=True,
        )
        self.sales = User.objects.create_user(
            username="t_sales", password=PWD, real_name="销售", role=Role.SALES, is_staff=True,
        )

    def test_notify_creates_with_all_fields(self):
        from apps.accounts.models import Importance, NotificationCategory
        from apps.accounts.services import notify
        n = notify(
            category=NotificationCategory.SITE_DONE, importance=Importance.HIGH,
            recipients=self.sales, title="完工", content="x",
            actor=self.admin, entity_type="project", entity_id=7,
        )
        self.assertEqual(n, 1)
        row = Notification.objects.get(recipient=self.sales)
        self.assertEqual(row.category, NotificationCategory.SITE_DONE)
        self.assertEqual(row.importance, Importance.HIGH)
        self.assertEqual(row.actor, self.admin)
        self.assertEqual(row.entity_id, 7)

    def test_notify_dedup_suppresses_within_window(self):
        from apps.accounts.models import NotificationCategory
        from apps.accounts.services import notify
        notify(category=NotificationCategory.SITE_DONE, recipients=self.sales, title="完工", content="x",
               entity_type="project", entity_id=7)
        second = notify(category=NotificationCategory.SITE_DONE, recipients=self.sales, title="完工", content="x",
                        entity_type="project", entity_id=7)
        self.assertEqual(second, 0)
        self.assertEqual(Notification.objects.filter(recipient=self.sales).count(), 1)
        # 不同 entity 不幂等
        third = notify(category=NotificationCategory.SITE_DONE, recipients=self.sales, title="完工", content="x",
                       entity_type="project", entity_id=8)
        self.assertEqual(third, 1)

    def test_notify_batch_and_empty(self):
        from apps.accounts.services import notify
        self.assertEqual(notify(category="pool_flow", recipients=[self.admin, self.sales], title="公海", content="x"), 2)
        self.assertEqual(notify(category="other", recipients=[], title="x", content="x"), 0)

    def test_notify_skips_inactive_recipient(self):
        from apps.accounts.services import notify
        dead = User.objects.create_user(
            username="t_dead", password=PWD, real_name="离职", role=Role.SALES, is_staff=True, is_active=False,
        )
        self.assertEqual(notify(category="other", recipients=[dead, self.sales], title="x", content="x"), 1)


class FlowNotifyTests(TestCase):
    """关键流转触发:成交转立项→咨询主管、释放公海→销售主管/总经办."""

    def setUp(self):
        self.sales = User.objects.create_user(
            username="f_sales", password=PWD, real_name="销售", role=Role.SALES, is_staff=True,
        )
        self.sales_lead = User.objects.create_user(
            username="f_slead", password=PWD, real_name="销售主管", role=Role.SALES_LEAD, is_staff=True,
        )
        self.lead = User.objects.create_user(
            username="f_lead", password=PWD, real_name="咨询主管", role=Role.CONSULTANT_LEAD, is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="f_admin", password=PWD, real_name="总办", role=Role.ADMIN,
            is_staff=True, is_superuser=True,
        )

    def test_mark_deal_notifies_consultant_lead(self):
        from apps.accounts.models import Notification, NotificationCategory
        from apps.customers.models import Customer, CustomerStatus
        from apps.projects.models import Project
        c = Customer.objects.create(
            company="单测成交X", contact_name="测", phone="13700000001",
            owner=self.sales, status=CustomerStatus.LEAD, created_by=self.sales,
        )
        cli = Client()
        cli.force_login(self.admin)
        cli.post("/admin/customers/customer/", {"action": "mark_deal", "_selected_action": [str(c.pk)]}, follow=True)
        n = Notification.objects.filter(category=NotificationCategory.DEAL_CONVERT).first()
        self.assertIsNotNone(n, "成交转立项应通知咨询主管")
        self.assertEqual(n.recipient, self.lead)
        self.assertEqual(n.importance, "high")
        self.assertTrue(Project.objects.filter(customer=c).exists())

    def test_release_to_pool_notifies_leads_and_admins(self):
        from apps.accounts.models import Notification, NotificationCategory, Role
        from apps.customers.models import Customer, CustomerStatus
        c = Customer.objects.create(
            company="单测公海X", contact_name="测", phone="13700000002",
            owner=self.sales, status=CustomerStatus.LEAD, created_by=self.sales,
        )
        cli = Client()
        cli.force_login(self.admin)
        cli.post("/admin/customers/customer/", {"action": "release_to_square", "_selected_action": [str(c.pk)], "apply": "1", "reason": "测试释放"}, follow=True)
        roles = set(
            Notification.objects.filter(category=NotificationCategory.POOL_FLOW)
            .values_list("recipient__role", flat=True)
        )
        self.assertIn(Role.SALES_LEAD, roles)
        self.assertIn(Role.ADMIN, roles)
