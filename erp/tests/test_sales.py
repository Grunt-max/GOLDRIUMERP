from decimal import Decimal
from datetime import date, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from erp.forms import CustomerForm, SaleLineForm
from erp.models import CompanyProfile, Customer, DailyActivity, Factory, GoldLedgerEntry, GoldPrice, Material, Order, Product, ProductAlias, ProductColor, ProductWeightProfile, PurchaseEntry, PurchaseSupplier, ReceivableAccount, SaleItem, SaleTransaction, UserAccessProfile, generate_transaction_no
from erp.product_catalog import rebuild_product_weight_profiles
from erp.views import monthly_sales_metrics


class SaleStructureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="mykim9853", password="test-pass-1234")
        cls.customer = Customer.objects.create(name="테스트 판매처", customer_type="sales", default_loss_rate=Decimal("5"))
        cls.material_14 = Material.objects.get(name="14K")
        cls.material_18 = Material.objects.get(name="18K")
        cls.material_24 = Material.objects.get(name="24K")
        cls.material_silver = Material.objects.get(name="925 Silver")
        cls.color_p = ProductColor.objects.get(code="P")
        Material.objects.filter(pk__in=[cls.material_14.pk, cls.material_18.pk]).update(default_loss_rate=Decimal("2"))
        cls.product = Product.objects.create(name="카탈로그 제품", code="CAT-001", material=cls.material_14, color=cls.color_p, default_weight=Decimal("2.000"), default_loss_rate=Decimal("3"), unit_price=1000)

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["basic_management_verified_user_id"] = self.user.pk
        session.save()

    def test_receivables_are_kept_separate_by_customer_sub_account(self):
        coco = ReceivableAccount.objects.create(customer=self.customer, name="코코 미수")
        rope = ReceivableAccount.objects.create(customer=self.customer, name="로프 미수")
        sale = SaleTransaction.objects.create(customer=self.customer, sale_date=date(2026, 8, 20))
        SaleItem.objects.create(
            transaction=sale, receivable_account=coco, entry_type="sale", model_number="COCO",
            material=self.material_24, weight=Decimal("10"), quantity=1, loss_rate=0, unit_price=10000,
        )
        SaleItem.objects.create(
            transaction=sale, receivable_account=rope, entry_type="sale", model_number="ROPE",
            material=self.material_24, weight=Decimal("7"), quantity=1, loss_rate=0, unit_price=7000,
        )
        payment = SaleTransaction.objects.create(customer=self.customer, sale_date=date(2026, 8, 21))
        SaleItem.objects.create(
            transaction=payment, receivable_account=coco, entry_type="payment", model_number="결제",
            material=self.material_24, weight=Decimal("3"), quantity=1, loss_rate=0, unit_price=3000,
        )

        response = self.client.get(reverse("erp:receivables_list"))
        rows = {row["account"].name: row for row in response.context["receivables"]}
        self.assertEqual(rows["코코 미수"]["gold_receivable"], Decimal("7.000"))
        self.assertEqual(rows["코코 미수"]["labor_receivable"], Decimal("7000"))
        self.assertEqual(rows["로프 미수"]["gold_receivable"], Decimal("7.000"))
        self.assertEqual(rows["로프 미수"]["labor_receivable"], Decimal("7000"))
        self.assertContains(response, "코코 미수")
        self.assertContains(response, "로프 미수")

    def test_account_opening_balance_replaces_pre_cutoff_history_and_adds_later_assigned_sales(self):
        self.customer.receivable_accounts_enabled = True
        self.customer.save(update_fields=["receivable_accounts_enabled"])
        coco = ReceivableAccount.objects.create(
            customer=self.customer, name="코코미수", opening_date=date(2026, 8, 25),
            opening_gold_balance=Decimal("118.586"), opening_labor_balance=Decimal("240000"),
        )
        old_sale = SaleTransaction.objects.create(customer=self.customer, sale_date=date(2026, 8, 20))
        SaleItem.objects.create(
            transaction=old_sale, entry_type="sale", model_number="과거자료",
            material=self.material_24, weight=Decimal("50"), quantity=1, loss_rate=0, unit_price=500000,
        )
        later_sale = SaleTransaction.objects.create(customer=self.customer, sale_date=date(2026, 9, 1))
        SaleItem.objects.create(
            transaction=later_sale, receivable_account=coco, entry_type="sale", model_number="코코대",
            material=self.material_24, weight=Decimal("2"), quantity=1, loss_rate=0, unit_price=1000,
        )

        response = self.client.get(reverse("erp:receivables_list"))
        row = next(row for row in response.context["receivables"] if row["account"] == coco)
        self.assertEqual(row["gold_receivable"], Decimal("120.586"))
        self.assertEqual(row["labor_receivable"], Decimal("241000"))
        self.assertFalse(any(row["account"] is None for row in response.context["receivables"]))
        summary = self.client.get(reverse("erp:customer_sales_summary", args=[self.customer.pk]), {"account": coco.pk}).json()
        self.assertEqual(summary["account_name"], "코코미수")
        self.assertEqual(summary["gold_receivable"], "120.586")
        self.assertEqual(summary["labor_receivable"], "241000")

    def test_newly_uploaded_product_image_is_downsized_before_storage(self):
        source = BytesIO()
        Image.new("RGB", (3200, 2400), (180, 140, 90)).save(source, format="PNG")
        upload = SimpleUploadedFile("large-photo.png", source.getvalue(), content_type="image/png")
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            product = Product.objects.create(
                name="다운사이징 테스트", code="RESIZE-001", unit_price=0, image=upload,
            )
            with Image.open(product.image.path) as stored:
                self.assertLessEqual(max(stored.size), 1600)
                self.assertEqual(stored.size, (1600, 1200))
                self.assertEqual(stored.format, "JPEG")
    def test_erp_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("erp:dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('erp:dashboard')}")
        login_page = self.client.get(reverse("login"))
        self.assertContains(login_page, "골드리움 킹")

    def test_basic_management_requires_master_password_again(self):
        session = self.client.session
        session.pop("basic_management_verified_user_id", None)
        session.save()

        settings_url = reverse("erp:material_list")
        response = self.client.get(settings_url)
        self.assertRedirects(
            response,
            f"{reverse('basic_management_login')}?next=%2Fsettings%2Fmaterials%2F",
        )
        self.assertContains(self.client.get(reverse("basic_management_login")), "기초관리 재인증")
        wrong = self.client.post(reverse("basic_management_login"), {
            "password": "wrong-password", "next": settings_url,
        })
        self.assertContains(wrong, "비밀번호가 올바르지 않습니다.")
        success = self.client.post(reverse("basic_management_login"), {
            "password": "test-pass-1234", "next": settings_url,
        })
        self.assertRedirects(success, settings_url)

    def test_non_master_cannot_access_basic_management(self):
        non_master = get_user_model().objects.create_user(username="employee", password="employee-pass")
        self.client.force_login(non_master)
        self.assertEqual(self.client.get(reverse("basic_management_login")).status_code, 403)
        self.assertEqual(self.client.get(reverse("erp:material_list")).status_code, 403)

    def test_master_can_create_employee_with_selected_view_permissions(self):
        page = self.client.get(reverse("access_management"))
        self.assertContains(page, "직원 조회 계정 관리")
        response = self.client.post(reverse("access_management"), {
            "action": "create", "create-username": "viewer",
            "create-password1": "Strong-view-pass-426!", "create-password2": "Strong-view-pass-426!",
            "sections": ["orders", "activities"],
        })
        self.assertRedirects(response, reverse("access_management"))
        employee = get_user_model().objects.get(username="viewer")
        self.assertEqual(employee.erp_access_profile.allowed_sections, ["orders", "activities"])
        self.assertFalse(employee.is_staff)

    def test_employee_is_limited_to_granted_read_only_pages(self):
        employee = get_user_model().objects.create_user(username="viewer", password="employee-pass-426!")
        UserAccessProfile.objects.create(user=employee, allowed_sections=["orders"])
        self.client.force_login(employee)
        self.assertEqual(self.client.get(reverse("erp:order_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("erp:sales_list")).status_code, 403)
        self.assertEqual(self.client.post(reverse("erp:order_create"), {}).status_code, 403)
        self.assertEqual(self.client.get(reverse("access_management")).status_code, 403)

    def test_material_weight_formulas(self):
        sale = SaleTransaction.objects.create(customer=self.customer)
        expected = {
            self.material_14: Decimal("1.193"),
            self.material_18: Decimal("1.530"),
            self.material_24: Decimal("2.000"),
            self.material_silver: Decimal("0.000"),
        }
        for index, (material, pure_weight) in enumerate(expected.items()):
            item = SaleItem.objects.create(transaction=sale, model_number=f"M-{index}", material=material, color=self.color_p, weight=Decimal("2"), quantity=2, loss_rate=Decimal("2"), unit_price=1000)
            self.assertEqual(item.pure_gold_weight, pure_weight)

    def test_gold_statistics_include_24k_but_exclude_silver_and_loss_is_14k_18k_only(self):
        sale = SaleTransaction.objects.create(customer=self.customer, sale_date=timezone.localdate())
        SaleItem.objects.create(
            transaction=sale, model_number="GOLD-24", material=self.material_24,
            weight=Decimal("3"), quantity=1, loss_rate=Decimal("9"), unit_price=0,
        )
        silver = SaleItem.objects.create(
            transaction=sale, model_number="SILVER", material=self.material_silver,
            weight=Decimal("10"), quantity=1, loss_rate=Decimal("10"), unit_price=5000,
        )
        sale.refresh_totals()
        metrics = monthly_sales_metrics(timezone.localdate().year, timezone.localdate().month)
        self.assertEqual(silver.pure_gold_weight, Decimal("0.000"))
        self.assertEqual(metrics["base_gold"], Decimal("3.000"))
        self.assertEqual(metrics["loss_gold"], Decimal("0.0000"))
        self.assertEqual(metrics["total_gold"], Decimal("3.000"))
        self.assertEqual(metrics["labor"], Decimal("5000"))

    def test_multiple_items_share_one_transaction_and_catalog_matches(self):
        data = {
            "header-customer": self.customer.pk, "header-ordered_at": "2026-08-20", "header-status": "new",
            "header-memo": "거래 비고",
            "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "1", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-entry_type": "sale", "lines-0-model_number": "CAT-001", "lines-0-material": self.material_14.pk, "lines-0-color": self.color_p.pk, "lines-0-weight": "2.000", "lines-0-loss_rate": "3", "lines-0-quantity": "2", "lines-0-unit_price": "", "lines-0-memo": "",
            "lines-1-entry_type": "payment", "lines-1-model_number": "", "lines-1-material": self.material_18.pk, "lines-1-color": "", "lines-1-weight": "1.000", "lines-1-loss_rate": "", "lines-1-quantity": "1", "lines-1-unit_price": "500", "lines-1-memo": "",
        }
        response = self.client.post(reverse("erp:sale_create"), data)
        self.assertRedirects(response, reverse("erp:sales_list"))
        sale = SaleTransaction.objects.get()
        self.assertEqual(sale.transaction_no, "26082000001")
        self.assertEqual(sale.items.count(), 2)
        catalog_item = sale.items.get(model_number="CAT-001")
        self.assertEqual(catalog_item.product, self.product)
        self.assertEqual(catalog_item.loss_rate, Decimal("3"))
        self.assertEqual(catalog_item.color, self.color_p)
        self.assertEqual(catalog_item.total_weight, Decimal("2.000"))
        payment_item = sale.items.get(entry_type="payment")
        self.assertEqual(payment_item.model_number, "결제")
        self.assertEqual(payment_item.material, self.material_24)
        self.assertEqual(payment_item.loss_rate, Decimal("0"))
        self.assertEqual(payment_item.quantity, 1)
        self.assertEqual(payment_item.memo, "결제일: 2026-08-20")
        self.assertEqual(catalog_item.memo, "직전 결제일: 2026-08-20")
        self.assertEqual(sale.cash_receivable, Decimal("0"))
        self.assertEqual(sale.total_labor_amount, Decimal("2000"))
        self.assertEqual(sale.paid_labor_amount, Decimal("500"))
        self.assertEqual(sale.labor_receivable, Decimal("1500"))
        self.assertEqual(sale.gold_receivable, Decimal("0.205"))
        summary = self.client.get(reverse("erp:customer_sales_summary", args=[self.customer.pk])).json()
        self.assertEqual(summary["default_loss_rate"], "5.00")
        self.assertEqual(summary["gold_receivable"], "0.205")
        self.assertEqual(summary["labor_receivable"], "1500")
        history = self.client.get(reverse("erp:customer_sales_history", args=[self.customer.pk]), {"date": "2026-08-20"}).json()
        self.assertEqual(len(history["results"]), 2)
        self.assertEqual(history["results"][0]["date"], "26-08-20")
        earlier = self.client.get(reverse("erp:customer_sales_history", args=[self.customer.pk]), {"date": "2026-08-19"}).json()
        self.assertEqual(earlier["results"], [])
        second = SaleTransaction.objects.create(
            transaction_no=generate_transaction_no(sale.sale_date),
            sale_date=sale.sale_date,
            customer=self.customer,
        )
        self.assertEqual(second.transaction_no, "26082000002")
        SaleItem.objects.create(
            transaction=second, entry_type="payment", model_number="결제",
            material=self.material_24, weight=Decimal("0.500"), quantity=1,
            loss_rate=0, unit_price=500,
        )
        second.refresh_totals()
        summary = self.client.get(reverse("erp:customer_sales_summary", args=[self.customer.pk])).json()
        self.assertEqual(summary["gold_receivable"], "-0.295")
        self.assertEqual(summary["labor_receivable"], "1000")
        returned = SaleItem.objects.create(
            transaction=second, entry_type="return", model_number="RET-001",
            material=self.material_14, weight=Decimal("1.000"), quantity=1,
            loss_rate=3, unit_price=300,
        )
        second.refresh_totals()
        self.assertEqual(returned.pure_gold_weight, Decimal("0.603"))
        summary = self.client.get(reverse("erp:customer_sales_summary", args=[self.customer.pk])).json()
        self.assertEqual(summary["gold_receivable"], "-0.898")
        self.assertEqual(summary["labor_receivable"], "700")
        ledger = self.client.get(reverse("erp:customer_ledger", args=[self.customer.pk]))
        self.assertContains(ledger, "RET-001")
        self.assertContains(ledger, "반품")

    def test_popup_sale_registration_returns_auto_close_page(self):
        data = {
            "_popup": "1",
            "header-customer": self.customer.pk, "header-ordered_at": "2026-08-22", "header-status": "new", "header-memo": "",
            "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-entry_type": "sale", "lines-0-model_number": "CAT-001", "lines-0-material": self.material_14.pk, "lines-0-color": self.color_p.pk,
            "lines-0-weight": "2.000", "lines-0-loss_rate": "3", "lines-0-quantity": "1.25", "lines-0-unit_price": "", "lines-0-memo": "",
        }
        response = self.client.post(reverse("erp:sale_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "정상 반영되었습니다.")
        self.assertContains(response, "window.opener.location.reload()")
        self.assertContains(response, "window.close()")
        self.assertEqual(SaleItem.objects.get().quantity, Decimal("1.25"))

    def test_catalog_weight_profiles_are_split_by_material_and_color(self):
        sale = SaleTransaction.objects.create(customer=self.customer)
        SaleItem.objects.create(
            transaction=sale, entry_type="sale", product=self.product, model_number=self.product.code,
            material=self.material_14, color=self.color_p, weight=Decimal("2.000"), quantity=1,
            loss_rate=0, unit_price=0,
        )
        SaleItem.objects.create(
            transaction=sale, entry_type="sale", product=self.product, model_number=self.product.code,
            material=self.material_14, color=self.color_p, weight=Decimal("4.000"), quantity=2,
            loss_rate=0, unit_price=0,
        )
        SaleItem.objects.create(
            transaction=sale, entry_type="sale", product=self.product, model_number=self.product.code,
            material=self.material_18, color=self.color_p, weight=Decimal("3.000"), quantity=1,
            loss_rate=0, unit_price=0,
        )
        rebuild_product_weight_profiles()
        profile_14 = ProductWeightProfile.objects.get(product=self.product, material=self.material_14, color=self.color_p)
        profile_18 = ProductWeightProfile.objects.get(product=self.product, material=self.material_18, color=self.color_p)
        self.assertEqual(profile_14.average_weight, Decimal("2.000"))
        self.assertEqual(profile_14.sale_sample_count, 2)
        self.assertEqual(profile_18.average_weight, Decimal("3.000"))

    def test_catalog_alias_matches_bn_variant(self):
        ProductAlias.objects.create(product=self.product, alias="CAT-001N")
        form = SaleLineForm(data={
            "entry_type": "sale", "model_number": "CAT-001N", "material": self.material_14.pk,
            "color": self.color_p.pk, "weight": "1", "loss_rate": "0", "quantity": "1",
            "unit_price": "0", "memo": "",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["catalog_product"], self.product)
        self.assertEqual(form.fields["quantity"].widget.attrs["step"], "any")

    def test_product_soft_delete_hides_and_restores_catalog_item(self):
        sale = SaleTransaction.objects.create(customer=self.customer)
        item = SaleItem.objects.create(
            transaction=sale, entry_type="sale", product=self.product, model_number=self.product.code,
            material=self.material_14, color=self.color_p, weight=Decimal("1"), quantity=1,
            loss_rate=0, unit_price=0,
        )
        response = self.client.post(reverse("erp:product_delete", args=[self.product.pk]))
        self.assertRedirects(response, reverse("erp:product_list"))
        self.product.refresh_from_db()
        item.refresh_from_db()
        self.assertTrue(self.product.is_deleted)
        self.assertFalse(self.product.active)
        self.assertEqual(item.product, self.product)
        self.assertNotContains(self.client.get(reverse("erp:product_list")), self.product.code)
        self.assertContains(self.client.get(reverse("erp:product_list") + "?include_deleted=1"), self.product.code)
        self.client.post(reverse("erp:product_restore", args=[self.product.pk]))
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_deleted)
        self.assertTrue(self.product.active)

    def test_sales_pages_render_new_structure(self):
        self.assertEqual(SaleLineForm().fields["unit_price"].initial, 0)
        for name in ("erp:sales_list", "erp:sale_create", "erp:receivables_list"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        sales_content = self.client.get(reverse("erp:sales_list")).content.decode()
        self.assertIn("순매출(판매-반품)", sales_content)
        self.assertIn("미수(판매-반품-결제)", sales_content)
        self.assertNotIn("재질별 중량 및 수량 합계", sales_content)
        content = self.client.get(reverse("erp:sale_create")).content.decode()
        self.assertIn("제품 행 추가", content)
        self.assertIn("empty-line-template", content)
        self.assertIn('"name": "24K"', content)
        self.assertIn("과거 매출 내역", content)
        self.assertEqual(content.count('class="sale-line"'), 6)
        self.assertNotIn('class="required-head">색상', content)

    def test_first_sale_after_prior_payment_gets_payment_date_memo(self):
        payment = SaleTransaction.objects.create(
            transaction_no="26082000001", sale_date=date(2026, 8, 20), customer=self.customer
        )
        SaleItem.objects.create(
            transaction=payment, entry_type="payment", model_number="결제",
            material=self.material_24, weight=Decimal("1.000"), quantity=1,
            loss_rate=0, unit_price=0,
        )
        payment.refresh_totals()
        response = self.client.post(reverse("erp:sale_create"), {
            "header-customer": self.customer.pk, "header-ordered_at": "2026-08-21", "header-status": "new", "header-memo": "",
            "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-entry_type": "sale", "lines-0-model_number": "CAT-001", "lines-0-material": self.material_14.pk, "lines-0-color": self.color_p.pk,
            "lines-0-weight": "2.000", "lines-0-loss_rate": "3", "lines-0-quantity": "1", "lines-0-unit_price": "", "lines-0-memo": "",
        })
        self.assertRedirects(response, reverse("erp:sales_list"))
        sold_item = SaleItem.objects.get(entry_type="sale")
        self.assertEqual(sold_item.memo, "직전 결제일: 2026-08-20")

    def test_transaction_number_opens_half_a4_statement(self):
        self.product.image = "products/statement-test.jpg"
        self.product.save(update_fields=["image"])
        ProductAlias.objects.create(product=self.product, alias="STATEMENT-01")
        sale = SaleTransaction.objects.create(
            transaction_no="26082200001", sale_date=date(2026, 8, 22), customer=self.customer
        )
        SaleItem.objects.create(
            transaction=sale, entry_type="sale", model_number="STATEMENT-01",
            material=self.material_14, color=self.color_p, weight=Decimal("1.000"),
            quantity=2, loss_rate=0, unit_price=1000,
        )
        sale.refresh_totals()
        detail_url = reverse("erp:sale_transaction_detail", args=[sale.pk])
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "거래 명세서", count=2)
        self.assertContains(response, f"[{self.customer.name}] 거래 명세서", count=2)
        self.assertContains(response, "공급자:</b> 골드리움", count=2)
        self.assertContains(response, "<b>STATEMENT-01</b>", count=2, html=True)
        self.assertContains(response, "/media/products/statement-test.jpg", count=2)
        self.assertContains(response, "거래 후 미수", count=2)
        self.assertNotContains(response, "합중량")
        self.assertContains(response, "14K 1.000", count=2)
        self.assertContains(response, "18K 0.000", count=2)
        self.assertContains(response, "24K 0.000", count=2)
        self.assertContains(self.client.get(reverse("erp:sales_list")), detail_url)

        settings_response = self.client.post(reverse("erp:company_profile_edit"), {
            "supplier_name": "테스트 공급자", "supplier_phone": "02-123-4567",
        })
        self.assertRedirects(settings_response, reverse("erp:material_list"))
        self.assertEqual(CompanyProfile.objects.get().supplier_name, "테스트 공급자")
        updated = self.client.get(detail_url)
        self.assertContains(updated, "공급자:</b> 테스트 공급자", count=2)
        self.assertContains(updated, "02-123-4567", count=2)
        self.customer.supplier_name_override = "거래처 전용 공급자"
        self.customer.save(update_fields=["supplier_name_override"])
        overridden = self.client.get(detail_url)
        self.assertContains(overridden, "공급자:</b> 거래처 전용 공급자", count=2)

    def test_customer_loss_rate_can_be_edited(self):
        response = self.client.post(reverse("erp:customer_edit", args=[self.customer.pk]), {
            "name": self.customer.name,
            "customer_type": "sales",
            "contact": "",
            "phone": "",
            "default_loss_rate": "7.25",
            "memo": "",
        })
        self.assertRedirects(response, reverse("erp:customer_list"))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.default_loss_rate, Decimal("7.25"))
        summary = self.client.get(reverse("erp:customer_sales_summary", args=[self.customer.pk])).json()
        self.assertEqual(summary["default_loss_rate"], "7.25")

    def test_customer_name_cannot_be_registered_twice_after_normalization(self):
        form = CustomerForm(data={
            "name": f"  {self.customer.name}  ",
            "customer_type": "sales",
            "contact": "",
            "phone": "",
            "default_loss_rate": "",
            "supplier_name_override": "",
            "memo": "",
        })
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["name"], ["이미 등록된 거래처명입니다."])

        with self.assertRaises(IntegrityError), transaction.atomic():
            Customer.objects.create(name=f" {self.customer.name} ", customer_type="sales")

    def test_customer_can_keep_its_name_when_edited(self):
        form = CustomerForm(data={
            "name": f" {self.customer.name} ",
            "customer_type": "sales",
            "contact": "수정 담당자",
            "phone": "",
            "default_loss_rate": "",
            "supplier_name_override": "",
            "memo": "",
        }, instance=self.customer)
        self.assertTrue(form.is_valid(), form.errors)
        updated = form.save()
        self.assertEqual(updated.name, self.customer.name)

    def test_sale_create_can_preselect_customer_from_receivables(self):
        outstanding = SaleTransaction.objects.create(customer=self.customer)
        SaleItem.objects.create(
            transaction=outstanding, entry_type="sale", model_number="바로판매",
            material=self.material_24, weight=Decimal("1.000"), quantity=1,
            loss_rate=0, unit_price=1000,
        )
        outstanding.refresh_totals()

        sale_url = f"{reverse('erp:sale_create')}?customer={self.customer.pk}"
        receivables = self.client.get(reverse("erp:receivables_list"))
        self.assertContains(receivables, sale_url, count=2)

        sale_form = self.client.get(sale_url)
        self.assertEqual(sale_form.context["header_form"]["customer"].value(), self.customer.pk)
        self.assertContains(sale_form, self.customer.name)

    def test_receivables_hide_customers_with_zero_gold_and_labor(self):
        settled_customer = Customer.objects.create(name="정산완료 거래처", customer_type="sales")
        SaleTransaction.objects.create(customer=settled_customer)
        response = self.client.get(reverse("erp:receivables_list"))
        self.assertNotContains(response, settled_customer.name)

        outstanding = SaleTransaction.objects.create(customer=self.customer)
        SaleItem.objects.create(
            transaction=outstanding,
            entry_type="sale",
            model_number="미수제품",
            material=self.material_24,
            weight=Decimal("1.000"),
            quantity=1,
            loss_rate=0,
            unit_price=0,
        )
        outstanding.refresh_totals()
        response = self.client.get(reverse("erp:receivables_list"))
        self.assertContains(response, self.customer.name)

    def test_receivables_and_advances_are_reported_separately_without_netting_customers(self):
        due_sale = SaleTransaction.objects.create(customer=self.customer)
        SaleItem.objects.create(
            transaction=due_sale, entry_type="sale", model_number="DUE",
            material=self.material_24, weight=Decimal("1.000"), quantity=1,
            loss_rate=0, unit_price=1000,
        )
        due_sale.refresh_totals()
        advance_customer = Customer.objects.create(name="선입거래처", customer_type="sales")
        advance_sale = SaleTransaction.objects.create(customer=advance_customer)
        SaleItem.objects.create(
            transaction=advance_sale, entry_type="payment", model_number="",
            material=self.material_24, weight=Decimal("2.000"), quantity=1,
            loss_rate=0, unit_price=2000,
        )
        advance_sale.refresh_totals()

        response = self.client.get(reverse("erp:receivables_list"))
        self.assertEqual(response.context["totals"]["gold_due"], Decimal("1.000"))
        self.assertEqual(response.context["totals"]["gold_advance"], Decimal("2.000"))
        self.assertEqual(response.context["totals"]["labor_due"], Decimal("1000"))
        self.assertEqual(response.context["totals"]["labor_advance"], Decimal("2000"))
        self.assertContains(response, "미수 거래처")
        self.assertContains(response, "선입 거래처")

    def test_legacy_adjustments_settle_gold_and_signed_labor(self):
        sale = SaleTransaction.objects.create(customer=self.customer)
        SaleItem.objects.create(
            transaction=sale, entry_type="sale", model_number="과거 판매",
            material=self.material_24, weight=Decimal("1.000"), quantity=1,
            loss_rate=0, unit_price=1000,
        )
        SaleItem.objects.create(
            transaction=sale, entry_type="wg", model_number="현금→순금",
            material=self.material_24, weight=Decimal("1.000"), quantity=1,
            loss_rate=0, unit_price=0,
        )
        SaleItem.objects.create(
            transaction=sale, entry_type="vd", model_number="과거 공임 조정",
            material=self.material_24, weight=Decimal("0"), quantity=1,
            loss_rate=0, unit_price=0, labor_total_override=Decimal("1000"),
        )
        sale.refresh_totals()
        self.assertEqual(sale.gold_receivable, Decimal("0.000"))
        self.assertEqual(sale.labor_receivable, Decimal("0"))
        summary = self.client.get(reverse("erp:customer_sales_summary", args=[self.customer.pk])).json()
        self.assertEqual(summary["gold_receivable"], "0.000")
        self.assertEqual(summary["labor_receivable"], "0")

    def test_quick_order_defaults_and_sale_fulfillment(self):
        response = self.client.post(reverse("erp:order_create"), {
            "source_type": "quick",
            "ordered_at": "2026-08-20",
            "due_date": "",
            "customer": self.customer.pk,
            "model_number": "",
            "raw_order_text": "14kp 1.3mm로프 5M\n18kp 1.3mm로프 5M",
            "material": "",
            "color": "",
            "delivery_type": "semi",
            "length_spec": "",
            "option_detail": "",
            "quantity": "3",
            "status": "new",
            "memo": "",
        })
        self.assertRedirects(response, reverse("erp:order_list"))
        self.assertEqual(Order.objects.filter(source_type="quick").count(), 2)
        order = Order.objects.get(source_type="quick", material=self.material_14)
        second_order = Order.objects.get(source_type="quick", material=self.material_18)
        self.assertEqual(str(order.due_date), "2026-08-27")
        self.assertEqual(order.model_number, "1.3mm로프")
        self.assertEqual(order.color, "핑크")
        self.assertEqual(order.thickness_spec, "")
        self.assertEqual(order.length_spec, "5M")
        self.assertEqual(order.delivery_type, "semi")
        self.assertEqual(order.remaining_quantity, Decimal("5"))
        self.assertEqual(second_order.model_number, "1.3mm로프")

        sale_data = {
            "header-customer": self.customer.pk, "header-ordered_at": "2026-08-22", "header-status": "new", "header-memo": "",
            "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-entry_type": "sale", "lines-0-model_number": "1.3mm로프", "lines-0-material": self.material_14.pk, "lines-0-color": self.color_p.pk, "lines-0-weight": "1.000",
            "lines-0-loss_rate": "", "lines-0-quantity": "2", "lines-0-unit_price": "0", "lines-0-memo": "",
        }
        self.assertRedirects(self.client.post(reverse("erp:sale_create"), sale_data), reverse("erp:sales_list"))
        order.refresh_from_db()
        self.assertEqual(order.fulfilled_quantity, 2)
        self.assertEqual(order.remaining_quantity, Decimal("3"))
        self.assertEqual(order.status, "partial")
        dashboard = self.client.get(reverse("erp:order_list"))
        self.assertContains(dashboard, "material-dashboard-14k")
        self.assertContains(dashboard, "material-dashboard-18k")
        self.assertContains(dashboard, "3M")
        self.assertContains(dashboard, "5M")
        self.assertContains(dashboard, "반제품")
        self.assertContains(dashboard, "order-customer-text")
        self.assertContains(dashboard, "matchOrderCustomer")
        self.assertContains(dashboard, "event.key!=='Enter'")
        self.assertContains(dashboard, reverse("erp:order_customer_outstanding"))
        popup = self.client.get(reverse("erp:order_customer_outstanding"))
        self.assertEqual(popup.status_code, 200)
        self.assertContains(popup, self.customer.name)
        self.assertContains(popup, "1.3mm로프")
        self.assertContains(popup, "3M")
        self.assertContains(popup, "5M")

    def test_quick_order_explicit_material_is_not_overwritten_by_catalog_default(self):
        Product.objects.create(
            name="1.3mm 기본 제품", code="1.3mm", material=self.material_14,
            color=self.color_p, default_weight=Decimal("1.000"), unit_price=1000,
        )
        response = self.client.post(reverse("erp:order_create"), {
            "source_type": "quick", "ordered_at": "2026-08-24", "due_date": "",
            "customer": self.customer.pk, "model_number": "",
            "raw_order_text": "18kw 1.3mm 5M", "material": "", "color": "",
            "delivery_type": "semi", "length_spec": "", "option_detail": "",
            "quantity": "1", "status": "new", "memo": "",
        })
        self.assertRedirects(response, reverse("erp:order_list"))
        order = Order.objects.get(raw_order_text="18kw 1.3mm 5M")
        self.assertEqual(order.material, self.material_18)
        self.assertEqual(order.color, "화이트")
        self.assertEqual(order.quantity, Decimal("5.00"))

    def test_quick_order_accepts_beige_as_korean_or_b_code(self):
        from erp.forms import parse_quick_order_lines
        parsed, invalid = parse_quick_order_lines("18K 베이지 코코체인 10M\n18K B 사볼대 5M")
        self.assertEqual(invalid, [])
        self.assertEqual([row["color"] for row in parsed], ["베이지", "베이지"])
        self.assertEqual([row["quantity"] for row in parsed], [Decimal("10"), Decimal("5")])

    def test_individual_order_item_can_be_completed_and_filtered(self):
        first = Order.objects.create(
            customer=self.customer, model_number="DELETE-ONE", ordered_at=date(2026, 8, 22),
            quantity=1, unit_price=0, source_type="quick",
        )
        second = Order.objects.create(
            customer=self.customer, model_number="KEEP-ONE", ordered_at=date(2026, 8, 22),
            quantity=1, unit_price=0, source_type="quick",
        )
        response = self.client.post(reverse("erp:order_complete", args=[first.pk]))
        self.assertRedirects(response, reverse("erp:order_list"))
        first.refresh_from_db()
        self.assertEqual(first.status, "done")
        self.assertEqual(first.fulfilled_quantity, first.quantity)
        self.assertEqual(first.completed_at, timezone.localdate())
        self.assertTrue(Order.objects.filter(pk=second.pk).exists())
        completed_page = self.client.get(reverse("erp:order_list"), {
            "date_type": "completed", "start_date": str(timezone.localdate()),
            "end_date": str(timezone.localdate()), "status": "done",
        })
        self.assertContains(completed_page, "DELETE-ONE")
        self.assertEqual(list(completed_page.context["orders"]), [first])
        self.assertContains(completed_page, "order-status-done")
        default_page = self.client.get(reverse("erp:order_list"))
        self.assertNotContains(default_page, "DELETE-ONE")
        included_page = self.client.get(reverse("erp:order_list"), {"include_completed": "1"})
        self.assertContains(included_page, "DELETE-ONE")
        self.assertContains(included_page, "완료 포함")
        outstanding_popup = self.client.get(reverse("erp:order_customer_outstanding"))
        self.assertNotContains(outstanding_popup, "DELETE-ONE")
        self.assertContains(outstanding_popup, "KEEP-ONE")

    def test_finished_quick_order_options_are_parsed_but_semi_options_are_ignored(self):
        response = self.client.post(reverse("erp:order_create"), {
            "source_type": "quick", "ordered_at": "2026-08-22", "due_date": "",
            "customer": self.customer.pk, "model_number": "",
            "raw_order_text": "14kp 1.3mm로프 42cm 2개 / 여유딸랑 / 0고리 마감\n18kp 1.3mm로프 5M / 반제품메모",
            "material": "", "color": "", "delivery_type": "finished",
            "length_spec": "", "option_detail": "", "quantity": "1",
            "status": "new", "memo": "",
        })
        self.assertRedirects(response, reverse("erp:order_list"))
        finished = Order.objects.get(material=self.material_14, ordered_at=date(2026, 8, 22))
        semi = Order.objects.get(material=self.material_18, ordered_at=date(2026, 8, 22))
        self.assertEqual(finished.delivery_type, "finished")
        self.assertEqual(finished.quantity, Decimal("2"))
        self.assertEqual(finished.option_detail, "여유딸랑 / 0고리 마감")
        self.assertEqual(semi.delivery_type, "semi")
        self.assertEqual(semi.option_detail, "")
        page = self.client.get(reverse("erp:order_list"))
        self.assertContains(page, "inline-quick-order-form")

    def test_order_numbers_pagination_edit_and_bulk_soft_delete(self):
        orders = [Order.objects.create(
            customer=self.customer, model_number=f"ORDER-{index:02d}",
            ordered_at=date(2026, 8, 22), quantity=1, unit_price=0,
        ) for index in range(12)]
        self.assertEqual(orders[0].transaction_no, "260822001")
        self.assertEqual(orders[-1].transaction_no, "260822012")
        page = self.client.get(reverse("erp:order_list"))
        self.assertEqual(len(page.context["orders"]), 10)
        self.assertContains(page, "30줄")
        self.assertContains(page, reverse("erp:order_edit", args=[orders[-1].pk]))
        self.assertNotContains(page, 'value="progress"')
        response = self.client.post(reverse("erp:order_bulk_action"), {
            "order_ids": [orders[0].pk], "action": "cancel",
        })
        self.assertRedirects(response, reverse("erp:order_list"))
        orders[0].refresh_from_db()
        self.assertEqual(orders[0].status, "cancel")
        self.client.post(reverse("erp:order_bulk_action"), {
            "order_ids": [orders[0].pk], "action": "delete",
        })
        orders[0].refresh_from_db()
        self.assertTrue(orders[0].is_deleted)
        self.assertNotContains(self.client.get(reverse("erp:order_list")), "ORDER-00")

    def test_order_end_date_defaults_today_and_dashboard_shows_open_and_overdue(self):
        overdue = Order.objects.create(
            customer=self.customer, model_number="OVERDUE-14K", material=self.material_14,
            color="핑크", ordered_at=date(2026, 8, 1), due_date=date(2026, 8, 8),
            delivery_type="finished", quantity=2, unit_price=0,
        )
        order_page = self.client.get(reverse("erp:order_list"))
        self.assertEqual(order_page.context["end_date"], str(timezone.localdate()))
        home = self.client.get(reverse("erp:dashboard"))
        self.assertContains(home, "14K 미출고 제품")
        self.assertContains(home, overdue.model_number)
        self.assertContains(home, "납기 경과 거래처")
        self.assertContains(home, self.customer.name)
        self.assertContains(home, overdue.model_number)
        self.assertNotContains(home, ">None<")
        self.assertContains(home, "최근 결제 내역")
        self.assertNotContains(home, 'dashboard-business" open')
        self.assertNotContains(home, "최근 주문")
        self.assertContains(home, "미수금")
        self.assertContains(home, "미수공임")

    @patch("erp.views.timezone.localdate", return_value=date(2026, 8, 22))
    def test_monthly_gold_metrics_and_daily_activity_calendar(self, _mock_localdate):
        GoldPrice.objects.create(
            market_type="wholesale", price_date=timezone.localdate(),
            source_price_per_gram=Decimal("100000"), source_price_per_don=Decimal("375000"),
        )
        daily_order = Order.objects.create(
            customer=self.customer, model_number="DAILY-ORDER", material=self.material_18,
            color="화이트", ordered_at=date(2026, 8, 22), quantity=1, unit_price=0,
        )
        sale = SaleTransaction.objects.create(customer=self.customer, sale_date=date(2026, 8, 10))
        item = SaleItem.objects.create(
            transaction=sale, entry_type="sale", model_number="MONTHLY-14K",
            material=self.material_14, weight=Decimal("30"), quantity=1,
            loss_rate=Decimal("5"), unit_price=10000,
        )
        sale.refresh_totals()
        home = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(home.context["month_metrics"]["base_gold"], Decimal("17.550"))
        self.assertEqual(home.context["month_metrics"]["loss_gold"], Decimal("0.8775"))
        self.assertEqual(home.context["month_metrics"]["total_gold"], Decimal("18.428"))
        self.assertEqual(home.context["month_metrics"]["labor"], Decimal("10000"))
        self.assertEqual(home.context["wholesale_loss_value"], Decimal("87750"))
        self.assertContains(home, "(87,750원)")
        self.assertContains(home, "현재 도매 시세 기준 환산액")
        self.assertContains(home, "8월 전체 순금 매출")
        self.assertContains(home, reverse("erp:monthly_customer_sales"), count=4)
        self.assertContains(home, "dashboard-arrow", count=4)
        monthly_page = self.client.get(reverse("erp:monthly_customer_sales"))
        self.assertContains(monthly_page, "2026년 08월 ~ 2026년 08월 거래처별 매출")
        self.assertEqual(monthly_page.context["period_end"], timezone.localdate())
        self.assertContains(monthly_page, "현재월은 오늘까지")
        self.assertContains(monthly_page, self.customer.name)
        self.assertEqual(monthly_page.context["rows"][0]["total_gold"], Decimal("18.4275"))
        self.assertContains(monthly_page, "0.88g")
        self.assertContains(monthly_page, "(87,750원)")
        self.assertContains(monthly_page, "전체 순금 매출")
        self.assertContains(monthly_page, 'class="monthly-sort-link', count=5)
        self.assertNotContains(monthly_page, ">수량<")
        sorted_page = self.client.get(reverse("erp:monthly_customer_sales"), {"month": "2026-08", "sort": "labor"})
        self.assertEqual(sorted_page.context["selected_sort"], "labor")
        self.assertContains(sorted_page, "매출 공임")
        july_sale = SaleTransaction.objects.create(customer=self.customer, sale_date=date(2026, 7, 15))
        SaleItem.objects.create(
            transaction=july_sale, entry_type="sale", model_number="JULY-14K",
            material=self.material_14, weight=Decimal("10"), quantity=1,
            loss_rate=Decimal("5"), unit_price=5000,
        )
        july_sale.refresh_totals()
        range_page = self.client.get(reverse("erp:monthly_customer_sales"), {
            "start_month": "2026-07", "end_month": "2026-08",
        })
        self.assertEqual(range_page.context["period_start"], date(2026, 7, 1))
        self.assertEqual(range_page.context["period_end"], timezone.localdate())
        self.assertEqual(range_page.context["totals"]["quantity"], Decimal("2"))
        self.assertEqual(range_page.context["totals"]["loss_value"], Decimal("117000"))
        self.assertContains(range_page, "2026년 07월 ~ 2026년 08월 거래처별 매출")
        response = self.client.post(reverse("erp:daily_activity_create"), {
            "activity_date": "2026-08-22", "content": "샘플 제작 및 출고 확인",
        })
        self.assertRedirects(response, reverse("erp:dashboard"))
        self.assertTrue(DailyActivity.objects.filter(content="샘플 제작 및 출고 확인").exists())
        activity_page = self.client.get(reverse("erp:daily_activity_list"), {"date": "2026-08-22", "month": "2026-08"})
        self.assertContains(activity_page, "샘플 제작 및 출고 확인")
        self.assertContains(activity_page, daily_order.model_number)
        self.assertContains(activity_page, f"{self.material_18.name} · 화이트 · {daily_order.model_number}")
        self.assertContains(activity_page, 'name="images"')
        self.assertContains(activity_page, 'enctype="multipart/form-data"')
        sale_day_page = self.client.get(reverse("erp:daily_activity_list"), {"date": "2026-08-10", "month": "2026-08"})
        self.assertContains(sale_day_page, "거래처별 판매·결제")
        self.assertContains(sale_day_page, "순금총중량(g)", count=2)
        self.assertNotContains(sale_day_page, "MONTHLY-14K")
        self.assertEqual(sale_day_page.context["day_customer_sales"][0]["sale_gold"], item.pure_gold_weight)

        item.is_deleted = True
        item.save(update_fields=["is_deleted"])
        deleted_sale_page = self.client.get(reverse("erp:daily_activity_list"), {"date": "2026-08-10", "month": "2026-08"})
        self.assertEqual(deleted_sale_page.context["day_customer_sales"], [])
        activity = DailyActivity.objects.get(content="샘플 제작 및 출고 확인")
        delete_response = self.client.post(reverse("erp:daily_activity_delete", args=[activity.pk]))
        self.assertEqual(delete_response.status_code, 302)
        activity.refresh_from_db()
        self.assertTrue(activity.is_deleted)
        self.assertNotContains(self.client.get(reverse("erp:daily_activity_list"), {"date": "2026-08-22", "month": "2026-08"}), "샘플 제작 및 출고 확인")
        calendar_context = self.client.get(reverse("erp:dashboard")).context["calendar_weeks"]
        august_22 = next(day for week in calendar_context for day in week if str(day["date"]) == "2026-08-22")
        self.assertEqual(august_22["order_count"], 1)

    def test_internal_gold_ledger_combines_payments_purchases_and_manual_entries(self):
        factory = Factory.objects.create(name="테스트 공장")
        issue = GoldLedgerEntry.objects.create(
            entry_date=date(2026, 8, 22), factory=factory, entry_type="issue",
            material=self.material_14, actual_weight=Decimal("30"), cash_amount=0,
        )
        self.assertEqual(issue.pure_gold_weight, Decimal("17.550"))
        sale = SaleTransaction.objects.create(sale_date=date(2026, 8, 22), customer=self.customer)
        SaleItem.objects.create(
            transaction=sale, entry_type="payment", model_number="결제", material=self.material_24,
            weight=Decimal("2"), quantity=1, loss_rate=0, unit_price=0,
        )
        supplier = PurchaseSupplier.objects.create(name="외부 공장", default_loss_rate=Decimal("5"))
        purchase = PurchaseEntry.objects.create(purchase_date=date(2026, 8, 22), supplier=supplier, material=self.material_18, actual_weight=Decimal("4"), loss_rate=Decimal("5"))
        self.assertEqual(purchase.pure_gold_weight, Decimal("3.150"))
        page = self.client.get(reverse("erp:gold_ledger_list"), {"start_date": "2026-08-01", "end_date": "2026-08-22"})
        self.assertContains(page, "거래처 금 결제")
        self.assertContains(page, "매입처 금매입량")
        self.assertNotContains(page, "타 공장 매입")
        self.assertEqual(page.context["summary"]["purchase_pure"], Decimal("3.150"))
        self.assertEqual(page.context["summary"]["purchase_loss"], Decimal("0.150"))
        self.assertEqual(page.context["summary"]["balance_effect"], Decimal("-15.550"))
        self.assertEqual(page.context["current_balance"], Decimal("-15.550"))
        purchase_page = self.client.get(reverse("erp:purchase_list"))
        self.assertContains(purchase_page, "외부 공장")
        GoldLedgerEntry.objects.create(
            entry_date=date(2026, 8, 22), factory=factory, entry_type="issue",
            destination_type="purchase_supplier", purchase_supplier=supplier,
            material=self.material_24, actual_weight=Decimal("2"), cash_amount=0,
        )
        activity = self.client.get(reverse("erp:daily_activity_list"), {"date": "2026-08-22", "month": "2026-08"})
        self.assertContains(activity, "금 수불")
        self.assertContains(activity, "금 불출")
        self.assertContains(activity, "외부 공장")
        self.client.post(reverse("erp:gold_ledger_delete", args=[issue.pk]))
        issue.refresh_from_db()
        self.assertTrue(issue.is_deleted)
        filtered = self.client.get(reverse("erp:gold_ledger_list"), {"start_date": "2026-08-01", "end_date": "2026-08-22"})
        self.assertNotContains(filtered, "17.550")

    def test_purchase_registration_saves_multiple_loss_rate_lines_under_one_number(self):
        supplier = PurchaseSupplier.objects.create(name="다중 매입 공장", default_loss_rate=Decimal("5"))
        response = self.client.post(reverse("erp:purchase_create"), {
            "header-purchase_date": "2026-08-22", "header-supplier": supplier.pk, "header-reference_no": "",
            "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-item_name": "14K 체인", "lines-0-material": self.material_14.pk, "lines-0-actual_weight": "10", "lines-0-loss_rate": "5", "lines-0-purchase_amount": "100000", "lines-0-memo": "14K 매입",
            "lines-1-item_name": "18K 장식", "lines-1-material": self.material_18.pk, "lines-1-actual_weight": "4", "lines-1-loss_rate": "2", "lines-1-purchase_amount": "50000", "lines-1-memo": "18K 매입",
        })
        self.assertRedirects(response, reverse("erp:purchase_list"))
        rows = list(PurchaseEntry.objects.filter(supplier=supplier).order_by("id"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].reference_no, rows[1].reference_no)
        self.assertIsNotNone(rows[0].batch_id)
        self.assertEqual(rows[0].batch_id, rows[1].batch_id)
        self.assertEqual(rows[0].pure_gold_weight, Decimal("6.143"))
        self.assertEqual(rows[1].pure_gold_weight, Decimal("3.060"))
        metrics = monthly_sales_metrics(2026, 8)
        self.assertEqual(metrics["purchase_base_gold"], Decimal("8.850"))
        self.assertEqual(metrics["purchase_loss_gold"], Decimal("0.3525"))
        self.assertEqual(metrics["purchase_labor"], Decimal("150000"))

        empty = self.client.post(reverse("erp:purchase_create"), {
            "header-purchase_date": "2026-08-22", "header-supplier": supplier.pk, "header-reference_no": "",
            "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
        })
        self.assertEqual(empty.status_code, 200)
        self.assertContains(empty, "아무것도 입력되지 않았습니다")
        self.assertEqual(PurchaseEntry.objects.filter(supplier=supplier).count(), 2)

    def test_sale_labor_input_accepts_thousand_separators(self):
        form = SaleLineForm(data={
            "entry_type": "sale", "model_number": "MONEY-TEST", "material": self.material_14.pk,
            "weight": "1.000", "loss_rate": "0", "quantity": "2", "unit_price": "₩ 20,000", "memo": "",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["unit_price"], Decimal("20000"))
        self.assertEqual(form.cleaned_data["unit_price"] * form.cleaned_data["quantity"], Decimal("40000"))

    def test_sale_quantity_accepts_two_decimals_and_rejects_three(self):
        base_data = {
            "entry_type": "sale", "model_number": "QTY-TEST", "material": self.material_14.pk,
            "weight": "1.000", "loss_rate": "0", "unit_price": "1000", "memo": "",
        }
        quantity_field = SaleLineForm().fields["quantity"]
        self.assertEqual(quantity_field.decimal_places, 2)
        self.assertEqual(quantity_field.widget.attrs["step"], "any")
        valid = SaleLineForm(data={**base_data, "quantity": "1.25"})
        self.assertTrue(valid.is_valid(), valid.errors)
        invalid = SaleLineForm(data={**base_data, "quantity": "1.001"})
        self.assertFalse(invalid.is_valid())
        self.assertIn("quantity", invalid.errors)

    def test_sale_item_soft_delete_excludes_totals_and_can_be_viewed(self):
        sale = SaleTransaction.objects.create(customer=self.customer)
        item = SaleItem.objects.create(
            id=2543,
            transaction=sale, entry_type="sale", model_number="SOFT-DELETE",
            material=self.material_24, weight=Decimal("1.000"), quantity=1,
            loss_rate=0, unit_price=1000,
        )
        sale.refresh_totals()
        self.assertEqual(sale.gold_receivable, Decimal("1.000"))
        self.assertEqual(sale.labor_receivable, Decimal("1000"))

        list_page = self.client.get(reverse("erp:sales_list"))
        self.assertContains(list_page, 'name="order_ids" value="2543"')
        response = self.client.post(reverse("erp:sales_soft_delete"), {"order_ids": ["2,543"]})
        self.assertRedirects(response, reverse("erp:sales_list"))
        item.refresh_from_db()
        sale.refresh_from_db()
        self.assertTrue(item.is_deleted)
        self.assertEqual(sale.gold_receivable, Decimal("0"))
        self.assertEqual(sale.labor_receivable, Decimal("0"))
        self.assertNotContains(self.client.get(reverse("erp:sales_list")), "SOFT-DELETE")
        deleted_page = self.client.get(reverse("erp:sales_list"), {"include_deleted": "1"})
        self.assertContains(deleted_page, "SOFT-DELETE")
        self.assertContains(deleted_page, "deleted-row")

    def test_sales_list_falls_back_to_latest_date_when_today_is_empty(self):
        latest_date = timezone.localdate() - timedelta(days=3)
        sale = SaleTransaction.objects.create(customer=self.customer, sale_date=latest_date)
        SaleItem.objects.create(
            transaction=sale, entry_type="sale", model_number="LATEST-SALE",
            material=self.material_24, weight=Decimal("1.000"), quantity=1,
            loss_rate=0, unit_price=1000,
        )
        response = self.client.get(reverse("erp:sales_list"))
        self.assertEqual(response.context["start_date"], latest_date.isoformat())
        self.assertEqual(response.context["end_date"], latest_date.isoformat())
        self.assertContains(response, "LATEST-SALE")

    def test_checked_sale_item_can_be_returned_once(self):
        sale = SaleTransaction.objects.create(
            customer=self.customer, sale_date=timezone.localdate() - timedelta(days=1)
        )
        original = SaleItem.objects.create(
            id=3543,
            transaction=sale, entry_type="sale", model_number="RETURN-ME",
            product=self.product, material=self.material_14, color=self.color_p,
            weight=Decimal("2.000"), quantity=2, loss_rate=Decimal("3"),
            unit_price=1000,
        )
        original.refresh_from_db()
        sale.refresh_totals()

        response = self.client.post(reverse("erp:sales_return"), {"order_ids": ["3,543"]})
        self.assertRedirects(response, reverse("erp:sales_list"))
        returned = SaleItem.objects.get(returned_from=original, is_deleted=False)
        self.assertEqual(returned.entry_type, "return")
        self.assertEqual(returned.transaction.sale_date, timezone.localdate())
        self.assertEqual(returned.model_number, original.model_number)
        self.assertEqual(returned.weight, original.weight)
        self.assertEqual(returned.quantity, original.quantity)
        self.assertEqual(returned.total_amount, original.total_amount)
        summary = self.client.get(reverse("erp:customer_sales_summary", args=[self.customer.pk])).json()
        self.assertEqual(summary["gold_receivable"], "0.000")
        self.assertEqual(summary["labor_receivable"], "0")

        self.client.post(reverse("erp:sales_return"), {"order_ids": [original.pk]})
        self.assertEqual(SaleItem.objects.filter(returned_from=original, is_deleted=False).count(), 1)

    def test_empty_sale_registration_is_rejected(self):
        data = {
            "header-customer": self.customer.pk,
            "header-ordered_at": "2026-08-20",
            "header-status": "new",
            "header-memo": "",
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "1",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-entry_type": "sale",
            "lines-0-model_number": "",
            "lines-0-material": "",
            "lines-0-weight": "",
            "lines-0-loss_rate": "",
            "lines-0-quantity": "1",
            "lines-0-unit_price": "",
            "lines-0-memo": "",
        }
        response = self.client.post(reverse("erp:sale_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "아무것도 입력되지 않았습니다. 주문 등록 실패")
        self.assertEqual(SaleTransaction.objects.count(), 0)

    def test_partially_entered_row_is_not_silently_skipped_when_later_row_is_valid(self):
        data = {
            "_popup": "1",
            "header-customer": self.customer.pk, "header-ordered_at": "2026-09-02", "header-status": "new", "header-memo": "",
            "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-entry_type": "sale", "lines-0-model_number": "", "lines-0-material": self.material_14.pk,
            "lines-0-color": self.color_p.pk, "lines-0-weight": "2.000", "lines-0-loss_rate": "3",
            "lines-0-quantity": "1", "lines-0-unit_price": "1000", "lines-0-memo": "",
            "lines-1-entry_type": "sale", "lines-1-model_number": "CAT-001", "lines-1-material": self.material_14.pk,
            "lines-1-color": self.color_p.pk, "lines-1-weight": "1.000", "lines-1-loss_rate": "3",
            "lines-1-quantity": "1", "lines-1-unit_price": "1000", "lines-1-memo": "",
        }
        response = self.client.post(reverse("erp:sale_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "등록되지 않았습니다.")
        self.assertContains(response, "입력한 행의 모델번호를 입력하세요.")
        self.assertNotContains(response, "finishSalePopup")
        self.assertEqual(SaleTransaction.objects.count(), 0)

    def test_extra_rows_with_only_automatic_defaults_are_ignored(self):
        data = {
            "header-customer": self.customer.pk, "header-ordered_at": "2026-09-02", "header-status": "new", "header-memo": "",
            "lines-TOTAL_FORMS": "5", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
        }
        for index in range(5):
            data.update({
                f"lines-{index}-entry_type": "sale", f"lines-{index}-model_number": "",
                f"lines-{index}-material": "", f"lines-{index}-color": "", f"lines-{index}-weight": "",
                f"lines-{index}-loss_rate": "5", f"lines-{index}-quantity": "1",
                f"lines-{index}-unit_price": "0", f"lines-{index}-memo": "",
            })
        for index in (0, 1):
            data.update({
                f"lines-{index}-model_number": "CAT-001", f"lines-{index}-material": self.material_14.pk,
                f"lines-{index}-color": self.color_p.pk, f"lines-{index}-weight": "1.000",
                f"lines-{index}-loss_rate": "3", f"lines-{index}-unit_price": "1000",
            })

        response = self.client.post(reverse("erp:sale_create"), data)
        self.assertRedirects(response, reverse("erp:sales_list"))
        self.assertEqual(SaleTransaction.objects.count(), 1)
        self.assertEqual(SaleItem.objects.count(), 2)

    def test_mixed_sale_and_negative_payment_preserves_signed_reversal(self):
        data = {
            "header-customer": self.customer.pk, "header-ordered_at": "2026-09-02", "header-status": "new", "header-memo": "",
            "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-entry_type": "sale", "lines-0-model_number": "CAT-001", "lines-0-material": self.material_14.pk,
            "lines-0-color": self.color_p.pk, "lines-0-weight": "2.000", "lines-0-loss_rate": "3",
            "lines-0-quantity": "1", "lines-0-unit_price": "1000", "lines-0-memo": "",
            "lines-1-entry_type": "payment", "lines-1-model_number": "", "lines-1-material": "",
            "lines-1-color": "", "lines-1-weight": "-1.000", "lines-1-loss_rate": "",
            "lines-1-quantity": "1", "lines-1-unit_price": "-500", "lines-1-memo": "",
        }
        response = self.client.post(reverse("erp:sale_create"), data)
        self.assertRedirects(response, reverse("erp:sales_list"))
        sale = SaleTransaction.objects.get()
        payment = sale.items.get(entry_type="payment")
        self.assertEqual(payment.weight, Decimal("-1.000"))
        self.assertEqual(payment.unit_price, Decimal("-500"))
        self.assertEqual(sale.paid_gold_weight, Decimal("-1.000"))
        self.assertEqual(sale.paid_labor_amount, Decimal("-500"))
        self.assertEqual(sale.gold_receivable, Decimal("2.205"))
        self.assertEqual(sale.labor_receivable, Decimal("1500"))

    def test_enabled_customer_account_is_selected_once_for_the_whole_transaction(self):
        self.customer.receivable_accounts_enabled = True
        self.customer.save(update_fields=["receivable_accounts_enabled"])
        account = ReceivableAccount.objects.create(customer=self.customer, name="로프 미수")
        data = {
            "header-customer": self.customer.pk, "header-receivable_account": account.pk,
            "header-ordered_at": "2026-09-02", "header-status": "new", "header-memo": "",
            "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-entry_type": "sale", "lines-0-model_number": "CAT-001", "lines-0-material": self.material_14.pk,
            "lines-0-color": self.color_p.pk, "lines-0-weight": "1", "lines-0-loss_rate": "3",
            "lines-0-quantity": "1", "lines-0-unit_price": "1000", "lines-0-memo": "",
            "lines-1-entry_type": "payment", "lines-1-model_number": "", "lines-1-material": "",
            "lines-1-color": "", "lines-1-weight": "0", "lines-1-loss_rate": "",
            "lines-1-quantity": "1", "lines-1-unit_price": "500", "lines-1-memo": "",
        }
        response = self.client.post(reverse("erp:sale_create"), data)
        self.assertRedirects(response, reverse("erp:sales_list"))
        self.assertEqual(set(SaleItem.objects.values_list("receivable_account_id", flat=True)), {account.pk})

        data["header-receivable_account"] = ""
        response = self.client.post(reverse("erp:sale_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "미수 계정을 선택하세요.")
