from datetime import date
from decimal import Decimal

from django.test import TestCase

from erp.legacy_sales_import import convert_transaction_no, normalize_customer_name, percent_from_multiplier
from erp.models import Customer, Material, SaleItem, SaleTransaction


class LegacyImportRuleTests(TestCase):
    def test_identifiers_and_legacy_names_are_normalized(self):
        self.assertEqual(convert_transaction_no("'202608210005"), "26082100005")
        self.assertEqual(normalize_customer_name("레이저테크_6프로"), "레이저테크")
        self.assertEqual(normalize_customer_name("세영체인8프로"), "세영체인")
        self.assertEqual(normalize_customer_name("에로스_판매_5프로"), "에로스")
        self.assertEqual(percent_from_multiplier("1.07"), Decimal("7.00"))

    def test_meter_quantity_and_settlement_weight_are_preserved(self):
        customer = Customer.objects.create(name="시험거래처")
        material, _ = Material.objects.get_or_create(name="14K", defaults={"purity_rate": Decimal("0.585"), "apply_loss_rate": True})
        sale = SaleTransaction.objects.create(
            transaction_no="26060100001", legacy_transaction_no="202606010001",
            sale_date=date(2026, 6, 1), customer=customer,
        )
        item = SaleItem.objects.create(
            transaction=sale, entry_type="sale", model_number="체인",
            material=material, weight=Decimal("3.560"), settlement_weight=Decimal("2.160"),
            quantity=Decimal("1.500"), sales_unit="meter", loss_rate=Decimal("10"), unit_price=Decimal("60000"),
        )
        self.assertEqual(item.quantity, Decimal("1.500"))
        self.assertEqual(item.pure_gold_weight, Decimal("1.390"))
        self.assertEqual(item.total_amount, Decimal("90000"))
