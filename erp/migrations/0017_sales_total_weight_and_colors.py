from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def create_colors_and_convert_weights(apps, schema_editor):
    ProductColor = apps.get_model("erp", "ProductColor")
    SaleItem = apps.get_model("erp", "SaleItem")
    for code, name in (("G", "골드"), ("P", "핑크"), ("W", "화이트"), ("B", "베이지")):
        ProductColor.objects.get_or_create(code=code, defaults={"name": name, "active": True})
    for item in SaleItem.objects.all().iterator():
        item.weight = (item.weight or Decimal("0")) * item.quantity
        item.save(update_fields=["weight"])


def restore_per_item_weights(apps, schema_editor):
    SaleItem = apps.get_model("erp", "SaleItem")
    for item in SaleItem.objects.all().iterator():
        if item.quantity:
            item.weight = item.weight / item.quantity
            item.save(update_fields=["weight"])


class Migration(migrations.Migration):
    dependencies = [("erp", "0016_order_amount_units")]

    operations = [
        migrations.CreateModel(
            name="ProductColor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=10, unique=True, verbose_name="색상코드")),
                ("name", models.CharField(max_length=30, verbose_name="색상명")),
                ("active", models.BooleanField(default=True, verbose_name="사용")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddField(
            model_name="product", name="color",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="erp.productcolor", verbose_name="기본 색상"),
        ),
        migrations.AddField(
            model_name="saleitem", name="color",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="erp.productcolor", verbose_name="색상"),
        ),
        migrations.AlterField(
            model_name="saleitem", name="weight",
            field=models.DecimalField(decimal_places=3, max_digits=10, verbose_name="총중량(g)"),
        ),
        migrations.RunPython(create_colors_and_convert_weights, restore_per_item_weights),
    ]
