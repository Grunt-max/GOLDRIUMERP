from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0040_goldprice_market_type_goldprice_source_price_per_don_and_more")]
    operations = [
        migrations.CreateModel(
            name="MarketplaceProduct",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("channel", models.CharField(choices=[("naver", "네이버 스마트스토어"), ("coupang", "쿠팡")], db_index=True, max_length=20, verbose_name="오픈마켓")),
                ("external_product_id", models.CharField(max_length=100, verbose_name="오픈마켓 상품번호")),
                ("name", models.CharField(max_length=500, verbose_name="상품명")),
                ("status", models.CharField(blank=True, max_length=80, verbose_name="판매상태")),
                ("category_code", models.CharField(blank=True, max_length=100, verbose_name="카테고리 코드")),
                ("product_url", models.URLField(blank=True, max_length=1000, verbose_name="상품 주소")),
                ("image_url", models.URLField(blank=True, max_length=1000, verbose_name="대표 이미지")),
                ("sale_price", models.DecimalField(blank=True, decimal_places=0, max_digits=14, null=True, verbose_name="판매가")),
                ("option_count", models.PositiveIntegerField(default=0, verbose_name="옵션 수")),
                ("raw_data", models.JSONField(blank=True, default=dict, verbose_name="API 원본")),
                ("synced_at", models.DateTimeField(auto_now=True, verbose_name="마지막 수집")),
            ],
            options={"ordering": ["channel", "name", "external_product_id"]},
        ),
        migrations.AddConstraint(
            model_name="marketplaceproduct",
            constraint=models.UniqueConstraint(fields=("channel", "external_product_id"), name="unique_marketplace_product"),
        ),
    ]
