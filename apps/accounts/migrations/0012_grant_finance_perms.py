# Grant finance role finance-management permissions on 2026-09-21 (boss directive)

from django.db import migrations


def grant_finance_perms(apps, schema_editor):
    """财务角色授予财务管理全套权限——老板 09-21 拍板:财务管理单独菜单.

    权限构成:view_finance_workbench(菜单)+customers 查看/改(减免坏账)+
    收款查看/录款/改(财务可自己录,同有确认权)。财务只读客户敏感字段
    (来源/电话/微信/QQ/意愿度/跟进),由 admin 层 get_list_display/fieldsets 屏蔽,不靠权限。"""
    User = apps.get_model("accounts", "User")
    Permission = apps.get_model("auth", "Permission")
    codes = [
        "view_finance_workbench",
        "view_customer", "change_customer",
        "view_receipt", "add_receipt", "change_receipt",
        "view_cost",
    ]
    perms = list(Permission.objects.filter(codename__in=codes, content_type__app_label__in=["accounts", "customers"]))
    users = list(User.objects.filter(role="finance"))
    n = 0
    for u in users:
        u.user_permissions.add(*perms)
        n += 1
    print(f"[data-migration] 财务管理权限 {len(perms)} 个 × 财务用户 {n} 个")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_grant_consult_lead_recycled_customer"),
    ]

    operations = [
        migrations.RunPython(grant_finance_perms, migrations.RunPython.noop),
    ]
