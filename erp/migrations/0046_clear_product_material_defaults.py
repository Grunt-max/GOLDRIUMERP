from django.db import migrations


def clear_catalog_defaults(apps, schema_editor):
    Product = apps.get_model("erp", "Product")
    Product.objects.update(material=None, color=None, default_weight=None, default_loss_rate=None)


class Migration(migrations.Migration):
    dependencies = [("erp", "0045_openmarketproduct_base_labor_cost_and_more")]
    operations = [migrations.RunPython(clear_catalog_defaults, migrations.RunPython.noop)]
