from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("erp", "0055_daily_activity_plan_status"),
    ]

    operations = [
        migrations.CreateModel(
            name="SaleCustomerChangeLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("transaction_no", models.CharField(db_index=True, max_length=30, verbose_name="거래번호")),
                ("reason", models.CharField(blank=True, max_length=200, verbose_name="변경 사유")),
                ("account_change_summary", models.CharField(blank=True, max_length=300, verbose_name="미수계정 처리")),
                ("changed_at", models.DateTimeField(auto_now_add=True, verbose_name="변경일시")),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sale_customer_change_logs", to=settings.AUTH_USER_MODEL, verbose_name="변경자")),
                ("new_customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_customer_changes_to", to="erp.customer", verbose_name="변경 후 거래처")),
                ("previous_customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_customer_changes_from", to="erp.customer", verbose_name="변경 전 거래처")),
                ("transaction", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="customer_change_logs", to="erp.saletransaction", verbose_name="판매거래")),
            ],
            options={"ordering": ["-changed_at", "-id"]},
        ),
    ]
