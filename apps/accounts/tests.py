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
