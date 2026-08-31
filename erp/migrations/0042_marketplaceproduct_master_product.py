from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("erp", "0041_marketplaceproduct")]

    operations = [
        migrations.AddField(
            model_name="marketplaceproduct",
            name="master_product",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="marketplace_snapshots", to="erp.product",
                verbose_name="ERP 마스터 상품",
            ),
        ),
    ]
