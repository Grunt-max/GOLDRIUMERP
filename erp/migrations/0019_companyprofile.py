from django.db import migrations, models


def create_default_profile(apps, schema_editor):
    CompanyProfile = apps.get_model("erp", "CompanyProfile")
    CompanyProfile.objects.get_or_create(
        singleton_key="default", defaults={"supplier_name": "골드리움", "supplier_phone": ""}
    )


class Migration(migrations.Migration):
    dependencies = [("erp", "0018_saleitem_soft_delete")]
    operations = [
        migrations.CreateModel(
            name="CompanyProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_key", models.CharField(default="default", editable=False, max_length=20, unique=True)),
                ("supplier_name", models.CharField(default="골드리움", max_length=100, verbose_name="공급자명")),
                ("supplier_phone", models.CharField(blank=True, max_length=30, verbose_name="공급자 전화번호")),
            ],
            options={"verbose_name": "회사 기본정보", "verbose_name_plural": "회사 기본정보"},
        ),
        migrations.RunPython(create_default_profile, migrations.RunPython.noop),
    ]
