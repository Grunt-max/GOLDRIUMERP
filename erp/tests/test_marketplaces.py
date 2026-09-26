import os
from decimal import Decimal
from datetime import date, datetime, timezone
from urllib.parse import parse_qs
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from erp.models import MarketplaceOrder, MarketplaceProduct, MarketplaceSettlement, OpenMarketChannelOffer, OpenMarketChannelOption, OpenMarketChannelSetting, OpenMarketProduct, OpenMarketVariant


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

    def test_workspace_creates_erp_product_from_name_only(self):
        response = self.client.post(reverse("erp:marketplace_workspace_create"), {"name": "GPT 목걸이"})
        product = OpenMarketProduct.objects.get(name="GPT 목걸이")
        self.assertRedirects(response, reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        self.assertEqual(product.code, f"ERP-{product.pk:06d}")
        self.assertEqual(product.workspace_status, "draft")
        self.assertEqual(product.target_channels, [])
        self.assertEqual(product.variants.count(), 0)
        self.assertEqual(set(product.channel_settings.values_list("channel", flat=True)), {"naver", "coupang"})
        page = self.client.get(reverse("erp:marketplace_workspace"))
        self.assertContains(page, "GPT 목걸이")
        self.assertContains(page, "ERP 상품 및 마켓 등록번호")
        edit_page = self.client.get(reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        self.assertEqual(edit_page.status_code, 200)
        self.assertContains(edit_page, "GPT 콘텐츠 준비")

    def test_workspace_silver_product_uses_silver_weight_cost(self):
        product = OpenMarketProduct.objects.create(
            code="SILVER-001", name="실버 목걸이", origin_country="대한민국",
            pricing_material="silver", default_weight=Decimal("10"), silver_price_per_gram=Decimal("1500"),
            base_labor_cost=Decimal("20000"), target_margin_rate=Decimal("30"), naver_fee_rate=Decimal("6"),
            coupang_fee_rate=Decimal("11"), target_channels=["naver"], workspace_status="draft",
        )
        variant = OpenMarketVariant.objects.create(product=product, sku="SILVER-001-S925", base_variant="S925")
        price = variant.cost_and_price("naver")
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
        internal = OpenMarketVariant.objects.create(product=product, sku="TEST-SILVER-S925", base_variant="S925")
        for channel, price in (("naver", 80000), ("coupang", 85000)):
            setting = OpenMarketChannelSetting.objects.create(product=product, channel=channel)
            OpenMarketChannelOption.objects.create(
                setting=setting, internal_variant=internal, seller_sku=f"TEST-{channel}",
                option_name_1="색상", option_value_1="실버", sale_price=price,
            )
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

    def test_workspace_allows_direct_channel_setting_edits(self):
        product = OpenMarketProduct.objects.create(code="DIRECT-001", name="직접 입력 상품")
        response = self.client.get(reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        self.assertContains(response, "마켓별 등록 정보 입력")
        self.assertContains(response, "상품정보고시 상세")
        self.assertContains(response, "네이버 판매중지 등록")
        self.assertContains(response, "고객에게 보일 옵션명")
        self.assertContains(response, "첫 번째 옵션값")
        self.assertContains(response, 'class="workspace-field"', html=False)
        self.assertContains(response, 'class="option-group-builder"', html=False)
        self.assertContains(response, 'name="workspace-naver-category_code"', html=False)
        naver_setting = product.channel_settings.get(channel="naver")
        naver_setting.upload_status = "failed"
        naver_setting.last_upload_error = "과거 오류"
        naver_setting.save(update_fields=["upload_status", "last_upload_error"])
        data = {
            "code": product.code, "name": product.name, "brand": "골드리움",
            "origin_country": "대한민국", "pricing_material": "gold", "silver_price_per_gram": "0",
            "base_labor_cost": "20000", "target_margin_rate": "30", "naver_fee_rate": "6",
            "coupang_fee_rate": "11", "target_channels": ["naver", "coupang"], "workspace_status": "draft",
        }
        for channel in ("naver", "coupang"):
            prefix = f"workspace-{channel}"
            data.update({
                f"{prefix}-category_code": "50004168" if channel == "naver" else "71588",
                f"{prefix}-channel_product_name": f"{channel} 직접 작성명",
                f"{prefix}-delivery_method": "DELIVERY", f"{prefix}-delivery_company_code": "CJGLS",
                f"{prefix}-outbound_location_code": "123", f"{prefix}-return_center_code": "456",
                f"{prefix}-delivery_fee_type": "FREE", f"{prefix}-delivery_fee": "0",
                f"{prefix}-return_fee": "3000", f"{prefix}-notice_type": "JEWELLERY",
                f"{prefix}-notice_data": '{}', f"{prefix}-extra_attributes": '{}',
                f"{prefix}-naver_origin_status": "SUSPENSION",
                f"{prefix}-naver_channel_display_status": "SUSPENSION",
                f"{prefix}-after_service_phone": "02-1234-5678",
                f"{prefix}-after_service_guide": "판매자에게 문의",
                f"{prefix}-origin_area_code": "00", f"{prefix}-origin_area_content": "",
                f"{prefix}-minor_purchasable": "on",
                f"{prefix}-options-TOTAL_FORMS": "0",
                f"{prefix}-options-INITIAL_FORMS": "0",
                f"{prefix}-options-MIN_NUM_FORMS": "0",
                f"{prefix}-options-MAX_NUM_FORMS": "1000",
            })
        response = self.client.post(reverse("erp:marketplace_workspace_edit", args=[product.pk]), data)
        self.assertRedirects(response, reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        self.assertEqual(product.channel_settings.get(channel="naver").channel_product_name, "naver 직접 작성명")
        self.assertEqual(product.channel_settings.get(channel="coupang").category_code, "71588")
        naver_setting.refresh_from_db()
        self.assertEqual(naver_setting.upload_status, "")
        self.assertEqual(naver_setting.last_upload_error, "")

    def test_workspace_registered_channel_shows_compact_completed_state(self):
        product = OpenMarketProduct.objects.create(code="UPLOADED-001", name="등록 완료 상품")
        setting = OpenMarketChannelSetting.objects.create(
            product=product, channel="naver", external_product_id="13715393051", upload_status="uploaded",
        )
        OpenMarketChannelSetting.objects.create(product=product, channel="coupang")

        response = self.client.get(reverse("erp:marketplace_workspace_edit", args=[product.pk]))

        self.assertContains(response, "외부 등록 완료")
        self.assertContains(response, "상품번호 13715393051")
        self.assertContains(response, "이미 등록된 상품")
        self.assertNotContains(response, "이미 등록된 상품입니다: 13715393051")

    def test_workspace_registry_shows_returned_channel_numbers(self):
        product = OpenMarketProduct.objects.create(code="REGISTRY-001", name="번호 관리 상품")
        OpenMarketChannelSetting.objects.create(
            product=product, channel="naver", external_product_id="90001",
            external_channel_product_id="50001", upload_status="uploaded",
        )
        OpenMarketChannelSetting.objects.create(
            product=product, channel="coupang", external_product_id="70001", upload_status="uploaded",
        )

        response = self.client.get(reverse("erp:marketplace_workspace"))

        self.assertContains(response, "번호 관리 상품")
        self.assertContains(response, "50001")
        self.assertContains(response, "원상품 90001")
        self.assertContains(response, "70001")

    def test_channel_option_generates_seller_sku_when_left_blank(self):
        product = OpenMarketProduct.objects.create(code="AUTO-001", name="자동 SKU 상품")
        setting = OpenMarketChannelSetting.objects.create(product=product, channel="naver")

        option = OpenMarketChannelOption.objects.create(
            setting=setting, option_name_1="색상", option_value_1="옐로우골드", sale_price=100000,
        )

        self.assertEqual(option.seller_sku, "AUTO-001-N-001")

    @patch("erp.views.publish_naver")
    def test_publish_saves_naver_origin_channel_and_option_ids(self, publish_naver):
        from django.core.files.uploadedfile import SimpleUploadedFile

        product = OpenMarketProduct.objects.create(
            code="RETURN-001", name="반환번호 상품", workspace_status="approved",
            target_channels=["naver"], image=SimpleUploadedFile("item.jpg", b"image"),
            detail_page_html="<p>상세</p>",
        )
        setting = OpenMarketChannelSetting.objects.create(
            product=product, channel="naver", category_code="50004168",
            after_service_phone="02-1234-5678", after_service_guide="판매자에게 문의",
        )
        option = OpenMarketChannelOption.objects.create(
            setting=setting, seller_sku="RETURN-001-N-001", option_name_1="색상",
            option_value_1="옐로우골드", sale_price=150000,
        )
        publish_naver.return_value = {
            "originProductNo": 90001,
            "smartstoreChannelProductNo": 50001,
            "originProduct": {"detailAttribute": {"optionInfo": {"optionCombinations": [{
                "id": 30001, "sellerManagerCode": "RETURN-001-N-001",
            }]}}},
        }

        response = self.client.post(reverse(
            "erp:marketplace_workspace_publish", args=[product.pk, "naver"],
        ))

        self.assertRedirects(response, reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        setting.refresh_from_db()
        option.refresh_from_db()
        self.assertEqual(setting.external_product_id, "90001")
        self.assertEqual(setting.external_channel_product_id, "50001")
        self.assertEqual(setting.upload_response["originProductNo"], 90001)
        self.assertEqual(option.external_option_id, "30001")

    def test_coupang_publish_id_accepts_object_response(self):
        from erp.views import _marketplace_publish_ids

        self.assertEqual(
            _marketplace_publish_ids("coupang", {"data": {"sellerProductId": 70001}}),
            (70001, None),
        )

    def test_workspace_saves_independent_channel_options(self):
        product = OpenMarketProduct.objects.create(code="OPTION-001", name="채널 옵션 상품")
        self.client.get(reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        data = {
            "code": product.code, "name": product.name, "pricing_material": "gold",
            "silver_price_per_gram": "0", "base_labor_cost": "0", "target_margin_rate": "30",
            "naver_fee_rate": "6", "coupang_fee_rate": "11", "workspace_status": "draft",
        }
        for channel in ("naver", "coupang"):
            prefix = f"workspace-{channel}"
            data.update({
                f"{prefix}-category_code": "1", f"{prefix}-channel_product_name": f"{channel} 상품",
                f"{prefix}-delivery_method": "DELIVERY", f"{prefix}-delivery_company_code": "",
                f"{prefix}-outbound_location_code": "", f"{prefix}-return_center_code": "",
                f"{prefix}-delivery_fee_type": "FREE", f"{prefix}-delivery_fee": "0",
                f"{prefix}-return_fee": "0", f"{prefix}-notice_type": "JEWELLERY",
                f"{prefix}-notice_data": '{}', f"{prefix}-extra_attributes": '{}',
                f"{prefix}-naver_origin_status": "SUSPENSION",
                f"{prefix}-naver_channel_display_status": "SUSPENSION",
                f"{prefix}-after_service_phone": "", f"{prefix}-after_service_guide": "",
                f"{prefix}-origin_area_code": "00", f"{prefix}-origin_area_content": "",
                f"{prefix}-minor_purchasable": "on",
                f"{prefix}-options-TOTAL_FORMS": "1", f"{prefix}-options-INITIAL_FORMS": "0",
                f"{prefix}-options-MIN_NUM_FORMS": "0", f"{prefix}-options-MAX_NUM_FORMS": "1000",
                f"{prefix}-options-0-seller_sku": f"{channel.upper()}-SKU-1",
                f"{prefix}-options-0-option_name_1": "색상" if channel == "naver" else "스타일",
                f"{prefix}-options-0-option_value_1": "로즈골드" if channel == "naver" else "기본형",
                f"{prefix}-options-0-option_name_2": "", f"{prefix}-options-0-option_value_2": "",
                f"{prefix}-options-0-original_price": "220000" if channel == "naver" else "230000",
                f"{prefix}-options-0-sale_price": "190000" if channel == "naver" else "205000",
                f"{prefix}-options-0-stock_quantity": "12", f"{prefix}-options-0-active": "on",
                f"{prefix}-options-0-sort_order": "0",
            })
        response = self.client.post(reverse("erp:marketplace_workspace_edit", args=[product.pk]), data)
        self.assertRedirects(response, reverse("erp:marketplace_workspace_edit", args=[product.pk]))
        naver = product.channel_settings.get(channel="naver").selling_options.get()
        coupang = product.channel_settings.get(channel="coupang").selling_options.get()
        self.assertEqual(naver.sale_price, Decimal("190000"))
        self.assertEqual(naver.original_price, Decimal("220000"))
        self.assertEqual(naver.option_name_1, "색상")
        self.assertEqual(coupang.sale_price, Decimal("205000"))
        self.assertEqual(coupang.original_price, Decimal("230000"))
        self.assertEqual(coupang.option_name_1, "스타일")

    def test_publish_payload_deep_merge_preserves_generated_fields(self):
        from erp.marketplace_publish import _deep_merge
        payload = {"originProduct": {"name": "ORO", "deliveryInfo": {"deliveryType": "DELIVERY"}}}
        _deep_merge(payload, {"originProduct": {"deliveryInfo": {"claimDeliveryInfo": {"shippingAddressId": 1}}}})
        self.assertEqual(payload["originProduct"]["name"], "ORO")
        self.assertEqual(payload["originProduct"]["deliveryInfo"]["deliveryType"], "DELIVERY")
        self.assertEqual(payload["originProduct"]["deliveryInfo"]["claimDeliveryInfo"]["shippingAddressId"], 1)

    @patch("erp.marketplace_publish._json_request")
    @patch("erp.marketplace_publish._naver_upload_image", return_value="https://example.com/product.jpg")
    @patch("erp.marketplace_publish._naver_token", return_value="token")
    def test_naver_publish_sends_suspended_status_and_required_details(self, _token, _image, request_api):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from erp.marketplace_publish import publish_naver
        from erp.models import OpenMarketChannelSetting
        product = OpenMarketProduct.objects.create(
            code="NAVER-001", name="네이버 상품", image=SimpleUploadedFile("item.jpg", b"image"),
            detail_page_html="<p>상세</p>", pricing_material="silver", silver_price_per_gram=1000,
            default_weight=Decimal("1"), base_labor_cost=10000,
        )
        OpenMarketVariant.objects.create(product=product, sku="NAVER-001-S925", base_variant="S925")
        setting = OpenMarketChannelSetting.objects.create(
            product=product, channel="naver", category_code="50004168",
            after_service_phone="02-1234-5678", after_service_guide="판매자에게 문의",
        )
        OpenMarketChannelOption.objects.create(
            setting=setting, seller_sku="NAVER-CUSTOM-1", option_name_1="길이",
            option_value_1="42cm", sale_price=210000, stock_quantity=7,
        )
        request_api.return_value = {"originProductNo": 1}
        publish_naver(product)
        body = request_api.call_args.kwargs["body"]
        self.assertEqual(body["originProduct"]["statusType"], "SUSPENSION")
        self.assertEqual(body["smartstoreChannelProduct"]["channelProductDisplayStatusType"], "SUSPENSION")
        detail = body["originProduct"]["detailAttribute"]
        self.assertEqual(detail["afterServiceInfo"]["afterServiceTelephoneNumber"], "02-1234-5678")
        self.assertEqual(detail["originAreaInfo"]["originAreaCode"], "00")
        self.assertTrue(detail["minorPurchasable"])
        combination = detail["optionInfo"]["optionCombinations"][0]
        self.assertEqual(combination["optionName1"], "42cm")
        self.assertEqual(combination["sellerManagerCode"], "NAVER-CUSTOM-1")
        self.assertEqual(body["originProduct"]["salePrice"], 210000)

    @patch("erp.marketplace_publish._json_request")
    @patch("erp.marketplace_publish._naver_upload_image", return_value="https://example.com/product.jpg")
    @patch("erp.marketplace_publish._naver_token", return_value="token")
    def test_naver_publish_converts_full_prices_to_base_discount_and_option_delta(self, _token, _image, request_api):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from erp.marketplace_publish import publish_naver

        product = OpenMarketProduct.objects.create(
            code="NAVER-DISCOUNT", name="네이버 할인 상품",
            image=SimpleUploadedFile("item.jpg", b"image"), detail_page_html="<p>상세</p>",
        )
        setting = OpenMarketChannelSetting.objects.create(product=product, channel="naver", category_code="50004168")
        OpenMarketChannelOption.objects.create(
            setting=setting, seller_sku="N-14K", option_name_1="주얼리 사이즈", option_value_1="14K",
            original_price=349900, sale_price=179800, stock_quantity=10,
        )
        OpenMarketChannelOption.objects.create(
            setting=setting, seller_sku="N-18K", option_name_1="주얼리 사이즈", option_value_1="18K",
            original_price=449900, sale_price=279800, stock_quantity=5,
        )
        request_api.return_value = {"originProductNo": 1}

        publish_naver(product)

        origin = request_api.call_args.kwargs["body"]["originProduct"]
        self.assertEqual(origin["salePrice"], 349900)
        self.assertEqual(origin["customerBenefit"]["immediateDiscountPolicy"]["discountMethod"], {
            "value": 170100, "unitType": "WON",
        })
        self.assertEqual([row["price"] for row in origin["detailAttribute"]["optionInfo"]["optionCombinations"]], [0, 100000])

    def test_naver_readiness_blocks_different_discount_amounts_by_option(self):
        from erp.marketplace_publish import publish_readiness

        product = OpenMarketProduct.objects.create(
            code="NAVER-BAD-DISCOUNT", name="할인 오류", workspace_status="approved",
            target_channels=["naver"], detail_page_html="<p>상세</p>",
        )
        setting = OpenMarketChannelSetting.objects.create(product=product, channel="naver", category_code="1")
        OpenMarketChannelOption.objects.create(
            setting=setting, seller_sku="A", option_name_1="재질", option_value_1="14K",
            original_price=300000, sale_price=200000,
        )
        OpenMarketChannelOption.objects.create(
            setting=setting, seller_sku="B", option_name_1="재질", option_value_1="18K",
            original_price=400000, sale_price=250000,
        )
        errors = publish_readiness(product, "naver")
        self.assertTrue(any("정상가 - 판매가" in error for error in errors))

    @patch.dict(os.environ, {
        "COUPANG_VENDOR_ID": "A0001", "COUPANG_ACCESS_KEY": "access", "COUPANG_SECRET_KEY": "secret",
    })
    @patch("erp.marketplace_publish._json_request")
    def test_coupang_publish_keeps_item_original_and_sale_prices(self, request_api):
        from erp.marketplace_publish import publish_coupang

        product = OpenMarketProduct.objects.create(code="COUPANG-PRICE", name="쿠팡 가격", detail_page_html="<p>상세</p>")
        setting = OpenMarketChannelSetting.objects.create(
            product=product, channel="coupang", category_code="71588",
            outbound_location_code="123", return_center_code="456",
        )
        OpenMarketChannelOption.objects.create(
            setting=setting, seller_sku="C-14K", option_name_1="사이즈", option_value_1="14K Gold",
            original_price=349900, sale_price=178800,
        )
        request_api.return_value = {"data": 1}

        publish_coupang(product, "https://example.com/item.jpg")

        item = request_api.call_args.kwargs["body"]["items"][0]
        self.assertEqual(item["originalPrice"], 349900)
        self.assertEqual(item["salePrice"], 178800)

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
