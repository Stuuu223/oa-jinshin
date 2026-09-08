"""资质需求旧数据从 JSON 列表转为逗号分隔文字."""
import json
from django.db import migrations


def convert_list_to_text(apps, schema_editor):
    Customer = apps.get_model("customers", "Customer")
    HistoricalCustomer = apps.get_model("customers", "HistoricalCustomer")
    for Model in (Customer, HistoricalCustomer):
        for obj in Model.objects.exclude(qualification_interest__isnull=True).exclude(qualification_interest=""):
            val = obj.qualification_interest
            if isinstance(val, str) and val.startswith("["):
                try:
                    items = json.loads(val)
                    if isinstance(items, list):
                        obj.qualification_interest = ", ".join(str(i) for i in items if i)
                        obj.save(update_fields=["qualification_interest"])
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0027_qualification_to_textfield"),
    ]

    operations = [
        migrations.RunPython(convert_list_to_text, migrations.RunPython.noop),
    ]
