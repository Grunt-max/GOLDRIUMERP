import os
from decimal import Decimal
from datetime import date, datetime, timezone
from urllib.parse import parse_qs
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from erp.models import MarketplaceOrder, MarketplaceProduct, MarketplaceSettlement, OpenMarketChannelOffer, OpenMarketProduct, OpenMarketVariant


class MarketplaceReadOnlyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="mykim9853", password="test-pass")
        self.client.force_login(self.user)
        session = self.client.session
        session["basic_management_verified_user_id"] = self.user.pk
        session.save()

    def test_page_is_explicitly_read_only(self):
        response = self.client.get(reverse("erp:marketplace_channel_items", args=["naver"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "읽기 전용")
        self.assertContains(response, "판매량과 매출은 주문 API 연결 후 추가됩니다")

    def test_workspace_creates_product_channels_and_default_variants(self):
        response = self.client.post(reverse("erp:marketplace_workspace_create"), {
            "code": "STUDIO-001", "name": "GPT 목걸이", "brand": "골드리움",
            "origin_country": "대한민국", "pricing_material": "gold", "silver_price_per_gram": "0",
            "base_labor_cost": "20000", "target_margin_rate": "30",
            "naver_fee_rate": "6", "coupang_fee_rate": "11", "target_channels": ["naver", "coupang"],
            "workspace_status": "review", "ai_instruction": "선물용으로 작성",
        })
        product = OpenMarketProduct.objects.get(code="STUDIO-001")
        self.assertRedirects(response, reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        self.assertEqual(product.workspace_status, "review")
        self.assertEqual(product.target_channels, ["naver", "coupang"])
        self.assertEqual(product.variants.count(), 4)
        self.assertEqual(set(product.channel_settings.values_list("channel", flat=True)), {"naver", "coupang"})
        page = self.client.get(reverse("erp:marketplace_workspace"))
        self.assertContains(page, "GPT 목걸이")
        edit_page = self.client.get(reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        self.assertEqual(edit_page.status_code, 200)
        self.assertContains(edit_page, "GPT 콘텐츠 준비")

    def test_workspace_silver_product_uses_silver_weight_cost(self):
        response = self.client.post(reverse("erp:marketplace_workspace_create"), {
            "code": "SILVER-001", "name": "실버 목걸이", "origin_country": "대한민국",
            "pricing_material": "silver", "default_weight": "10", "silver_price_per_gram": "1500",
            "base_labor_cost": "20000", "target_margin_rate": "30", "naver_fee_rate": "6",
            "coupang_fee_rate": "11", "target_channels": ["naver"], "workspace_status": "draft",
        })
        product = OpenMarketProduct.objects.get(code="SILVER-001")
        self.assertRedirects(response, reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        self.assertEqual(list(product.variants.values_list("base_variant", flat=True)), ["S925"])
        price = product.variants.get().cost_and_price("naver")
        self.assertEqual(price["gold_cost"], Decimal("15000"))
        self.assertEqual(price["total_cost"], Decimal("35000"))

    @patch("erp.views.generate_product_content")
    def test_workspace_generates_and_saves_channel_content(self, generate):
        product = OpenMarketProduct.objects.create(code="AI-001", name="AI 목걸이")
        generate.return_value = {
            "naver_name": "네이버용 목걸이", "coupang_name": "쿠팡용 목걸이",
            "summary": "상품 요약", "detail_html": "<div><h2>상세 설명</h2></div>", "sections": [],
        }
        response = self.client.post(reverse("erp:marketplace_workspace_generate", args=[product.pk]))
        self.assertRedirects(response, reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        product.refresh_from_db()
        self.assertEqual(product.description, "상품 요약")
        self.assertIn("상세 설명", product.detail_page_html)
        self.assertEqual(product.channel_settings.get(channel="naver").channel_product_name, "네이버용 목걸이")
        self.assertEqual(product.channel_settings.get(channel="coupang").channel_product_name, "쿠팡용 목걸이")

    def test_workspace_internal_preview_never_calls_external_publish_api(self):
        product = OpenMarketProduct.objects.create(
            code="TEST-SILVER", name="테스트 실버", workspace_status="approved",
            target_channels=["naver", "coupang"], pricing_material="silver",
            default_weight=Decimal("10"), silver_price_per_gram=Decimal("1500"), base_labor_cost=20000,
        )
        OpenMarketVariant.objects.create(product=product, sku="TEST-SILVER-S925", base_variant="S925")
        with patch("erp.views.publish_naver") as publish_naver, patch("erp.views.publish_coupang") as publish_coupang:
            response = self.client.post(reverse("erp:marketplace_workspace_simulate", args=[product.pk, "naver"]))
        self.assertRedirects(response, reverse("erp:marketplace_channel_items", args=["naver"]))
        publish_naver.assert_not_called()
        publish_coupang.assert_not_called()
        listing = MarketplaceProduct.objects.get(channel="naver", external_product_id="TEST-TEST-SILVER-naver")
        self.assertEqual(listing.status, "TEST_PREVIEW")
        self.assertTrue(listing.raw_data["testPreview"])
        self.assertEqual(listing.normalized_offers.count(), 1)
        response = self.client.post(reverse("erp:marketplace_workspace_simulate", args=[product.pk, "naver"]), {"action": "clear"})
        self.assertRedirects(response, reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        self.assertFalse(MarketplaceProduct.objects.filter(pk=listing.pk).exists())

    def test_channel_sales_aggregates_order_based_net_sales(self):
        MarketplaceSettlement.objects.create(
            channel="coupang", external_key="NP-1", external_order_id="N-1",
            recognized_on=date(2026, 9, 10), product_name="목걸이", quantity=2,
            sale_amount=200000, refund_amount=50000, fee_amount=10000, settlement_amount=140000,
        )
        response = self.client.get(reverse("erp:marketplace_sales_overview"), {
            "start": "2026-09-01", "end": "2026-09-30",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "150,000원")
        self.assertContains(response, "상품별 정산 매출")
        self.assertContains(response, "목걸이")

    @patch.dict(os.environ, {"NAVER_COMMERCE_CLIENT_ID": "id", "NAVER_COMMERCE_CLIENT_SECRET": "secret"})
    @patch("erp.views.fetch_naver_settlements")
    def test_order_sync_updates_same_product_order_without_duplicates(self, fetch_orders):
        base = {
            "external_key": "NP-1", "external_order_id": "N-1", "recognized_on": date(2026, 9, 10),
            "settlement_on": date(2026, 9, 11), "sale_type": "SALE", "product_name": "목걸이",
            "option_name": "14K", "quantity": 1, "sale_amount": 100000, "refund_amount": 0,
            "fee_amount": 10000, "settlement_amount": 90000, "raw_data": {},
        }
        fetch_orders.return_value = [base]
        url = reverse("erp:marketplace_order_sync", args=["naver"])
        self.client.post(url, {"start": "2026-09-01", "end": "2026-09-30"})
        fetch_orders.return_value = [{**base, "sale_amount": 0, "refund_amount": 100000, "settlement_amount": -100000}]
        self.client.post(url, {"start": "2026-09-01", "end": "2026-09-30"})
        self.assertEqual(MarketplaceSettlement.objects.count(), 1)
        self.assertEqual(MarketplaceSettlement.objects.get().refund_amount, Decimal("100000"))

    @patch("erp.marketplaces.time.sleep")
    @patch("erp.marketplaces._json_request")
    @patch("erp.marketplaces._naver_token", return_value="token")
    def test_naver_order_range_is_split_into_api_safe_days(self, token, json_request, sleep):
        from erp.marketplaces import fetch_naver_orders

        json_request.return_value = {"data": {"contents": [], "pagination": {"hasNext": False}}}
        fetch_naver_orders(date(2026, 9, 18), date(2026, 9, 20))
        self.assertEqual(json_request.call_count, 3)
        self.assertIn("from=2026-09-18T00%3A00%3A00.000%2B09%3A00", json_request.call_args_list[0].args[0])
        self.assertIn("to=2026-09-20T23%3A59%3A59.999%2B09%3A00", json_request.call_args_list[2].args[0])

    def test_marketplace_snapshot_can_create_or_link_erp_master(self):
        snapshot = MarketplaceProduct.objects.create(
            channel="coupang", external_product_id="reverse-1", name="역등록 목걸이",
            sale_price=100000, raw_data={"items": []},
        )
        response = self.client.post(reverse("erp:marketplace_product_import", args=[snapshot.pk]), {
            "action": "create", "code": "REVERSE-001", "name": "ERP 역등록 목걸이",
        })
        self.assertRedirects(response, reverse("erp:marketplace_product_detail", args=[snapshot.pk]))
        master = OpenMarketProduct.objects.get(code="REVERSE-001")
        self.assertFalse(master.active)
        self.assertEqual(master.variants.count(), 4)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.master_product, master)

        other = OpenMarketProduct.objects.create(name="기존 상품", code="EXISTING-001")
        response = self.client.post(reverse("erp:marketplace_product_import", args=[snapshot.pk]), {
            "action": "link", "master_product": other.pk,
        })
        self.assertRedirects(response, reverse("erp:marketplace_product_detail", args=[snapshot.pk]))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.master_product, other)

    def test_coupang_relative_image_path_is_normalized(self):
        from erp.views import _coupang_image_url
        self.assertEqual(
            _coupang_image_url("vendor_inventory/sample.png"),
            "https://thumbnail6.coupangcdn.com/thumbnails/remote/492x492ex/image/vendor_inventory/sample.png",
        )

    def test_master_product_builds_different_naver_and_coupang_drafts(self):
        product = OpenMarketProduct.objects.create(name="마스터 목걸이", code="MASTER-001")
        for code in ("14KY", "14KP", "18KY", "18KP"):
            OpenMarketVariant.objects.create(product=product, sku=f"MASTER-001-{code}", base_variant=code,
                                             weight=Decimal("2.5"), labor_cost=50000)
        from erp.marketplace_transformers import build_channel_preview

        preview = build_channel_preview(product)
        self.assertEqual([row["code"] for row in preview["variants"]], ["14KY", "14KP", "18KY", "18KP"])
        self.assertEqual(preview["naver"]["strategy"], "COMBINATION_OPTIONS")
        self.assertEqual(preview["naver"]["options"][0]["optionName1"], "14K")
        self.assertEqual(preview["coupang"]["strategy"], "INDEPENDENT_VENDOR_ITEMS")
        self.assertEqual(preview["coupang"]["items"][3]["itemName"], "18KP")
        page = self.client.get(reverse("erp:marketplace_master_products"))
        self.assertContains(page, "MASTER-001")
        detail = self.client.get(reverse("erp:marketplace_master_product_detail", args=[product.pk]))
        self.assertContains(detail, "공통 기준 옵션")
        self.assertContains(detail, "14KY")
        self.assertContains(detail, "18KP")

    def test_only_exact_market_names_are_grouped(self):
        naver = MarketplaceProduct.objects.create(
            channel="naver", external_product_id="n-1", name="14K 동일 목걸이", raw_data={}
        )
        coupang = MarketplaceProduct.objects.create(
            channel="coupang", external_product_id="c-1", name="[오로링주얼리] 14K 동일 목걸이", raw_data={}
        )
        similar = MarketplaceProduct.objects.create(
            channel="coupang", external_product_id="c-2", name="14K 비슷한 목걸이", raw_data={}
        )
        from erp.open_market_matching import group_exact_marketplace_products

        result = group_exact_marketplace_products()
        naver.refresh_from_db()
        coupang.refresh_from_db()
        similar.refresh_from_db()
        self.assertEqual(result["grouped"], 1)
        self.assertEqual(naver.master_product, coupang.master_product)
        self.assertEqual(naver.master_product.variants.count(), 4)
        self.assertIsNone(similar.master_product)
        page = self.client.get(reverse("erp:marketplace_master_product_detail", args=[naver.master_product.pk]))
        self.assertContains(page, "실제 옵션 비교")

    def test_master_pricing_uses_gold_price_fee_and_margin(self):
        from erp.models import GoldPrice
        product = OpenMarketProduct.objects.create(
            code="PRICE-001", name="가격 상품", default_weight=Decimal("2.000"),
            base_labor_cost=Decimal("20000"), target_margin_rate=Decimal("30"),
            naver_fee_rate=Decimal("6"), coupang_fee_rate=Decimal("11"),
        )
        variant = OpenMarketVariant.objects.create(product=product, sku="PRICE-001-14KY", base_variant="14KY")
        GoldPrice.objects.create(market_type="wholesale", price_date="2026-08-23",
                                 source_price_per_gram=100000, source_price_per_don=375000)
        self.assertEqual(variant.cost_and_price("naver")["gold_cost"], Decimal("117000"))
        self.assertGreater(variant.cost_and_price("coupang")["sale_price"],
                           variant.cost_and_price("naver")["sale_price"])
        detail = self.client.get(reverse("erp:marketplace_master_product_detail", args=[product.pk]))
        self.assertContains(detail, "중량·금시세·마진 판매가")
        self.assertContains(detail, "ERP 공통 필드")

    @patch.dict(os.environ, {"NAVER_COMMERCE_CLIENT_ID": "id", "NAVER_COMMERCE_CLIENT_SECRET": "secret"})
    @patch("erp.views.fetch_naver_products")
    def test_naver_sync_stores_snapshot_without_mutation_api(self, fetch_products):
        fetch_products.return_value = [{
            "originProductNo": 12345,
            "originProduct": {"name": "14K 테스트 목걸이", "salePrice": 250000,
                "statusType": "SALE", "leafCategoryId": "50000000",
                "detailAttribute": {"optionInfo": {"optionCombinations": [{"id": 1}, {"id": 2}]}}},
        }]
        response = self.client.post(reverse("erp:marketplace_sync", args=["naver"]))
        self.assertRedirects(response, reverse("erp:marketplace_channel_items", args=["naver"]))
        saved = MarketplaceProduct.objects.get(channel="naver", external_product_id="12345")
        self.assertEqual(saved.name, "14K 테스트 목걸이")
        self.assertEqual(saved.sale_price, 250000)
        self.assertEqual(saved.option_count, 2)
        self.assertEqual(saved.normalized_offers.count(), 2)
        self.assertTrue(OpenMarketChannelOffer.objects.filter(listing=saved, external_option_id="1").exists())

    @patch.dict(os.environ, {}, clear=True)
    def test_sync_without_credentials_does_not_call_api(self):
        response = self.client.post(reverse("erp:marketplace_sync", args=["coupang"]), follow=True)
        self.assertContains(response, "COUPANG_ACCESS_KEY")
        self.assertFalse(MarketplaceProduct.objects.exists())

    def test_naver_display_price_includes_discount_and_option_additions(self):
        product = MarketplaceProduct.objects.create(
            channel="naver", external_product_id="display-price", name="가격 테스트",
            sale_price=Decimal("520000"), option_count=3,
            raw_data={
                "searchProduct": {"channelProducts": [{"discountedPrice": 120000}]},
                "originProduct": {"salePrice": 520000, "detailAttribute": {"optionInfo": {
                    "optionCombinations": [
                        {"price": 0, "optionName1": "14K", "optionName2": "35cm", "stockQuantity": 3},
                        {"price": 45000, "optionName1": "14K", "optionName2": "38cm", "stockQuantity": 2},
                        {"price": 205700, "optionName1": "18K", "optionName2": "40cm", "stockQuantity": 1},
                    ],
                }}},
            },
        )
        self.assertEqual(product.display_price, Decimal("120000"))
        self.assertEqual(product.option_display_price_min, Decimal("120000"))
        self.assertEqual(product.option_display_price_max, Decimal("325700"))
        self.assertEqual(product.option_price_limit, Decimal("260000.0"))
        self.assertTrue(product.option_price_rule_ok)
        response = self.client.get(reverse("erp:marketplace_channel_items", args=["naver"]))
        self.assertContains(response, "기본 노출가")
        self.assertContains(response, "120,000원")
        self.assertContains(response, "325,700원")
        self.assertContains(response, reverse("erp:marketplace_product_detail", args=[product.pk]))
        detail = self.client.get(reverse("erp:marketplace_product_detail", args=[product.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "14K / 35cm")
        self.assertContains(detail, "18K / 40cm")
        self.assertContains(detail, "최종 노출가")
        self.assertContains(detail, "50% 규정")

    def test_naver_simple_options_are_shown_in_detail(self):
        product = MarketplaceProduct.objects.create(
            channel="naver", external_product_id="simple-option", name="단독 옵션 테스트",
            sale_price=Decimal("100000"), option_count=2,
            raw_data={"originProduct": {"salePrice": 100000, "detailAttribute": {"optionInfo": {
                "optionSimple": [
                    {"groupName": "반지 호수", "name": "10호", "usable": True},
                    {"groupName": "반지 호수", "name": "11호", "usable": False},
                ]
            }}}},
        )
        detail = self.client.get(reverse("erp:marketplace_product_detail", args=[product.pk]))
        self.assertContains(detail, "단독형", count=2)
        self.assertContains(detail, "반지 호수 / 10호")
        self.assertContains(detail, "반지 호수 / 11호")
        self.assertContains(detail, "중지")

    @patch.dict(os.environ, {"COUPANG_ACCESS_KEY": "access", "COUPANG_SECRET_KEY": "secret", "COUPANG_VENDOR_ID": "A00012345"})
    @patch("erp.marketplaces.time.sleep")
    @patch("erp.marketplaces._json_request")
    def test_coupang_fetch_loads_each_product_detail_with_vendor_items(self, json_request, sleep):
        from erp.marketplaces import fetch_coupang_products

        json_request.side_effect = [
            {"data": [{"sellerProductId": 777, "sellerProductName": "쿠팡 목걸이"}], "nextToken": ""},
            {"data": {"sellerProductId": 777, "items": [{"vendorItemId": 888, "salePrice": 120000}]}},
        ]
        rows = fetch_coupang_products()
        self.assertEqual(rows[0]["items"][0]["vendorItemId"], 888)
        self.assertEqual(rows[0]["listSummary"]["sellerProductName"], "쿠팡 목걸이")
        self.assertIn("/seller-products/777", json_request.call_args_list[1].args[0])

    def test_coupang_vendor_items_keep_independent_prices(self):
        product = MarketplaceProduct.objects.create(
            channel="coupang", external_product_id="777", name="쿠팡 옵션 테스트",
            sale_price=Decimal("150000"), option_count=2,
            raw_data={"items": [
                {"vendorItemId": 888, "itemName": "14K / 36cm", "originalPrice": 150000, "salePrice": 120000},
                {"vendorItemId": 889, "itemName": "18K / 40cm", "originalPrice": 300000, "salePrice": 270000},
            ]},
        )
        self.assertEqual(product.display_price, Decimal("120000"))
        self.assertEqual(product.option_display_price_min, Decimal("120000"))
        self.assertEqual(product.option_display_price_max, Decimal("270000"))
        detail = self.client.get(reverse("erp:marketplace_product_detail", args=[product.pk]))
        self.assertContains(detail, "vendorItemId")
        self.assertContains(detail, "888")
        self.assertContains(detail, "14K / 36cm")
        self.assertContains(detail, "270,000원")
        self.assertNotContains(detail, "50% 규정")

    @patch.dict(os.environ, {
        "NAVER_COMMERCE_CLIENT_ID": "client-id",
        "NAVER_COMMERCE_CLIENT_SECRET": "$2b$12$abcdefghijklmnopqrstuu",
    })
    @patch("erp.marketplaces.urlopen")
    @patch("bcrypt.hashpw")
    def test_naver_token_uses_form_content_type_and_client_credentials(self, hashpw, urlopen):
        from erp import marketplaces

        hashpw.return_value = b"bcrypt-result+/"
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b'{"access_token":"token"}'
        self.assertEqual(marketplaces._naver_token(), "token")
        request = urlopen.call_args.args[0]
        body = parse_qs(request.data.decode())
        self.assertEqual(request.headers["Content-type"], "application/x-www-form-urlencoded")
        self.assertEqual(body["grant_type"], ["client_credentials"])
        self.assertEqual(body["type"], ["SELF"])
        self.assertEqual(body["client_secret_sign"], ["YmNyeXB0LXJlc3VsdCsv"])
