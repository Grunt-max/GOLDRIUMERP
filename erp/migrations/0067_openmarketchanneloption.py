from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("erp", "0066_openmarketchannelsetting_naver_required_fields")]

    operations = [
        migrations.CreateModel(
            name="OpenMarketChannelOption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("seller_sku", models.CharField(max_length=100, verbose_name="채널 판매자 SKU")),
                ("option_name_1", models.CharField(default="선택", max_length=50, verbose_name="옵션명 1")),
                ("option_value_1", models.CharField(max_length=100, verbose_name="옵션값 1")),
                ("option_name_2", models.CharField(blank=True, max_length=50, verbose_name="옵션명 2")),
                ("option_value_2", models.CharField(blank=True, max_length=100, verbose_name="옵션값 2")),
                ("sale_price", models.DecimalField(decimal_places=0, max_digits=14, verbose_name="채널 판매가")),
                ("stock_quantity", models.PositiveIntegerField(default=999, verbose_name="채널 재고")),
                ("active", models.BooleanField(default=True, verbose_name="등록 사용")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="표시 순서")),
                ("internal_variant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="channel_options", to="erp.openmarketvariant", verbose_name="연결 내부 원가 기준")),
                ("setting", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="selling_options", to="erp.openmarketchannelsetting", verbose_name="마켓 등록 설정")),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
        migrations.AddConstraint(
            model_name="openmarketchanneloption",
            constraint=models.UniqueConstraint(fields=("setting", "seller_sku"), name="unique_channel_seller_sku"),
        ),
    ]
