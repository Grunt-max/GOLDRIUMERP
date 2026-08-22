from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0019_companyprofile")]
    operations = [
        migrations.AddField(
            model_name="customer",
            name="supplier_name_override",
            field=models.CharField(blank=True, max_length=100, verbose_name="명세서 공급자명"),
        ),
    ]
