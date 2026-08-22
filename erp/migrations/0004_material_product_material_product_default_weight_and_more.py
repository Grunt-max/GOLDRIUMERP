import django.db.models.deletion
from django.db import migrations, models


def seed_materials(apps, schema_editor):
    Material = apps.get_model("erp", "Material")
    materials = [
        ("14K", "0.5850", True),
        ("18K", "0.7500", True),
        ("24K", "1.0000", False),
        ("925 Silver", "0.9250", False),
    ]
    for name, purity_rate, apply_loss_rate in materials:
        Material.objects.get_or_create(name=name, defaults={
            "purity_rate": purity_rate,
            "default_loss_rate": "0.00",
            "apply_loss_rate": apply_loss_rate,
            "active": True,
        })


class Migration(migrations.Migration):
    dependencies = [("erp", "0003_remove_customer_loss_rate")]

    operations = [
        migrations.CreateModel(
            name="Material",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=30, unique=True, verbose_name="재질명")),
                ("purity_rate", models.DecimalField(decimal_places=4, default=1, max_digits=6, verbose_name="순도")),
                ("default_loss_rate", models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name="기본 해리율(%)")),
                ("apply_loss_rate", models.BooleanField(default=True, verbose_name="해리율 적용")),
                ("active", models.BooleanField(default=True, verbose_name="사용")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AlterField(
            model_name="product", name="code",
            field=models.CharField(max_length=40, unique=True, verbose_name="모델번호"),
        ),
        migrations.AddField(
            model_name="product", name="default_weight",
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True, verbose_name="기본 중량(g)"),
        ),
        migrations.AddField(
            model_name="product", name="material",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="erp.material", verbose_name="기본 재질"),
        ),
        migrations.AddField(
            model_name="order", name="loss_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name="해리율(%)"),
        ),
        migrations.AddField(
            model_name="order", name="model_number",
            field=models.CharField(default="", max_length=40, verbose_name="모델번호"),
        ),
        migrations.AddField(
            model_name="order", name="pure_gold_weight",
            field=models.DecimalField(decimal_places=3, default=0, max_digits=12, verbose_name="순금 환산중량(g)"),
        ),
        migrations.AddField(
            model_name="order", name="transaction_no",
            field=models.CharField(blank=True, db_index=True, max_length=30, verbose_name="거래번호"),
        ),
        migrations.AddField(
            model_name="order", name="weight",
            field=models.DecimalField(decimal_places=3, default=0, max_digits=10, verbose_name="개당 중량(g)"),
        ),
        migrations.AddField(
            model_name="order", name="material",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="erp.material", verbose_name="재질"),
        ),
        migrations.RunPython(seed_materials, migrations.RunPython.noop),
    ]
