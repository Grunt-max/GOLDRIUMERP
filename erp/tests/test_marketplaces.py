import os
from decimal import Decimal
from urllib.parse import parse_qs
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from erp.models import MarketplaceProduct, OpenMarketChannelOffer, OpenMarketProduct, OpenMarketVariant


class MarketplaceReadOnlyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="mykim9853", password="test-pass")
        self.client.force_login(self.user)

    def test_page_is_explicitly_read_only(self):
        response = self.client.get(reverse("erp:marketplace_channel_items", args=["naver"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "읽기 전용")
        self.assertContains(response, "판매량과 매출은 주문 API 연결 후 추가됩니다")

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
