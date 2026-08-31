from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("erp", "0042_marketplaceproduct_master_product")]

    operations = [
        migrations.CreateModel(
            name="OpenMarketProduct",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=40, unique=True, verbose_name="오픈마켓 상품번호")),
                ("name", models.CharField(max_length=200, verbose_name="마스터 상품명")),
                ("brand", models.CharField(blank=True, max_length=100, verbose_name="브랜드")),
                ("category", models.CharField(blank=True, max_length=100, verbose_name="공통 카테고리")),
                ("description", models.TextField(blank=True, verbose_name="상세페이지 원본")),
                ("image", models.FileField(blank=True, upload_to="open_market/products/", verbose_name="대표사진")),
                ("active", models.BooleanField(default=False, verbose_name="운영 상품")),
                ("memo", models.TextField(blank=True, verbose_name="메모")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="OpenMarketProductImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.FileField(upload_to="open_market/products/additional/", verbose_name="추가사진")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="순서")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="additional_images", to="erp.openmarketproduct")),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
        migrations.CreateModel(
            name="OpenMarketVariant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sku", models.CharField(max_length=100, unique=True, verbose_name="내부 SKU")),
                ("base_variant", models.CharField(choices=[("14KY", "14K 옐로우"), ("14KP", "14K 핑크"), ("18KY", "18K 옐로우"), ("18KP", "18K 핑크"), ("ETC", "기타")], default="ETC", max_length=10, verbose_name="기본 변형")),
                ("specifications", models.JSONField(blank=True, default=dict, verbose_name="세부 규격")),
                ("weight", models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name="기준 중량(g)")),
                ("labor_cost", models.DecimalField(decimal_places=0, default=0, max_digits=14, verbose_name="공임 원가")),
                ("active", models.BooleanField(default=True, verbose_name="사용")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="variants", to="erp.openmarketproduct")),
            ],
            options={
                "ordering": ["product__code", "base_variant", "sku"],
                "constraints": [models.UniqueConstraint(fields=("product", "base_variant", "specifications"), name="unique_open_market_variant_spec")],
            },
        ),
        migrations.AlterField(
            model_name="marketplaceproduct",
            name="master_product",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="marketplace_snapshots", to="erp.openmarketproduct", verbose_name="오픈마켓 마스터 상품"),
        ),
        migrations.CreateModel(
            name="OpenMarketChannelOffer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_option_id", models.CharField(max_length=100, verbose_name="채널 옵션 ID")),
                ("option_name", models.CharField(blank=True, max_length=500, verbose_name="채널 옵션명")),
                ("original_price", models.DecimalField(blank=True, decimal_places=0, max_digits=14, null=True, verbose_name="정상가")),
                ("sale_price", models.DecimalField(blank=True, decimal_places=0, max_digits=14, null=True, verbose_name="판매가")),
                ("additional_price", models.DecimalField(decimal_places=0, default=0, max_digits=14, verbose_name="옵션 추가금")),
                ("display_price", models.DecimalField(blank=True, decimal_places=0, max_digits=14, null=True, verbose_name="최종 노출가")),
                ("stock_quantity", models.IntegerField(blank=True, null=True, verbose_name="재고")),
                ("sale_status", models.CharField(blank=True, max_length=50, verbose_name="옵션 판매상태")),
                ("raw_attributes", models.JSONField(blank=True, default=dict, verbose_name="원본 옵션 속성")),
                ("synced_at", models.DateTimeField(auto_now=True)),
                ("listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="normalized_offers", to="erp.marketplaceproduct")),
                ("master_variant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="channel_offers", to="erp.openmarketvariant")),
            ],
            options={
                "ordering": ["listing", "option_name", "external_option_id"],
                "constraints": [models.UniqueConstraint(fields=("listing", "external_option_id"), name="unique_market_channel_offer")],
            },
        ),
        migrations.CreateModel(
            name="OpenMarketMatchCandidate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name_score", models.DecimalField(decimal_places=4, default=0, max_digits=5, verbose_name="상품명 유사도")),
                ("image_score", models.DecimalField(blank=True, decimal_places=4, max_digits=5, null=True, verbose_name="사진 유사도")),
                ("option_score", models.DecimalField(blank=True, decimal_places=4, max_digits=5, null=True, verbose_name="옵션 유사도")),
                ("status", models.CharField(choices=[("pending", "확인 필요"), ("confirmed", "동일 상품"), ("rejected", "다른 상품"), ("excluded", "제외")], default="pending", max_length=20, verbose_name="판정")),
                ("reason", models.CharField(blank=True, max_length=500, verbose_name="판정 근거")),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("coupang_listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="coupang_match_candidates", to="erp.marketplaceproduct")),
                ("naver_listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="naver_match_candidates", to="erp.marketplaceproduct")),
            ],
            options={
                "ordering": ["status", "-name_score", "id"],
                "constraints": [models.UniqueConstraint(fields=("naver_listing", "coupang_listing"), name="unique_open_market_match_pair")],
            },
        ),
    ]
