from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("erp", "0036_goldledgerentry_destination_and_closing"),
    ]

    operations = [
        migrations.AddField(
            model_name="saleitem",
            name="returned_from",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="return_items",
                to="erp.saleitem",
                verbose_name="원판매 품목",
            ),
        ),
    ]
