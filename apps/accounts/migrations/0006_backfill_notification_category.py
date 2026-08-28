"""存量通知回填 category——按历史标题关键词映射到新的事件类型(2026-08-29 升级).

升级前通知无 category 字段(迁移 0005 统一置为 other),这里把历史 4 类已知通知
按标题关键词回填,消费端角标/筛选立即可用;importance 保持默认 medium。
"""
from django.db import migrations


def backfill_categories(apps, schema_editor):
    Notification = apps.get_model("accounts", "Notification")
    rules = [
        ("撞单", "duplicate"),            # 撞单提醒 → 总经办
        ("客户分配", "assign_customer"),   # 公海调配/分配客户
        ("建站任务已承接", "site_taken"),   # 技术承接建站 → 咨询
        ("站点交接信息已更新", "site_info"),  # 站点信息更新 → 技术
    ]
    for keyword, category in rules:
        Notification.objects.filter(category="other", title__contains=keyword).update(category=category)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_notification_actor_notification_category_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_categories, noop),
    ]
