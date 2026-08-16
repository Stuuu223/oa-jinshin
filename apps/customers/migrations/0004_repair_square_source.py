"""修复客户池广场释放写坏 source 字段的存量数据.

旧版 release_to_square 直接把"客户池广场-XX"整串写进 source,绕过 choices
且超出 max_length=16（SQLite 不强制所以能存,换库/再编辑即报错）。
本迁移把脏值归位为 source="square",署名回填到 square_released_by。
"""
from django.db import migrations

PREFIX = "客户池广场-"
VALID_SOURCES = {"referral", "inbound", "ad", "square", "other"}


def repair(apps, schema_editor):
    Customer = apps.get_model("customers", "Customer")
    User = apps.get_model("accounts", "User")
    for c in Customer.objects.exclude(source__in=VALID_SOURCES):
        if c.source.startswith(PREFIX) and not c.square_released_by_id:
            releaser_name = c.source[len(PREFIX):]
            user = User.objects.filter(real_name=releaser_name).first()
            if user:
                c.square_released_by = user
        c.source = "square"
        c.save(update_fields=["source", "square_released_by"])


def unrepair(apps, schema_editor):
    pass  # 原脏值不可还原,回滚保持 square + square_released_by 组合


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0003_recycledcustomer_customer_duplicate_flagged_at_and_more"),
    ]

    operations = [
        migrations.RunPython(repair, unrepair),
    ]
