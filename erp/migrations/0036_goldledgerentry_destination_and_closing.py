from django.db import migrations, models
import django.db.models.deletion


def mark_existing_closing(apps, schema_editor):
    GoldLedgerEntry = apps.get_model("erp", "GoldLedgerEntry")
    GoldLedgerEntry.objects.filter(reference_no="2026-08-21 전량마감").update(is_closing_transfer=True)


class Migration(migrations.Migration):
    dependencies = [("erp", "0035_companyprofile_weight_decimal_places")]

    operations = [
        migrations.AddField(
            model_name="goldledgerentry",
            name="destination_type",
            field=models.CharField(choices=[("own_factory", "우리공장"), ("purchase_supplier", "매입처")], default="own_factory", max_length=20, verbose_name="불출 목적지"),
        ),
        migrations.AddField(
            model_name="goldledgerentry",
            name="purchase_supplier",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="gold_ledger_entries", to="erp.purchasesupplier", verbose_name="매입처"),
        ),
        migrations.AddField(
            model_name="goldledgerentry",
            name="is_closing_transfer",
            field=models.BooleanField(db_index=True, default=False, verbose_name="전량 불출 마감"),
        ),
        migrations.RunPython(mark_existing_closing, migrations.RunPython.noop),
    ]
