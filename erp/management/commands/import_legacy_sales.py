import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from erp.legacy_sales_import import read_legacy_sales
from erp.models import (
    Customer, CustomerAlias, DailySaleSequence, Material, Product, ProductAlias,
    ProductColor, PurchaseSupplier, SaleItem, SaleTransaction,
)


class Command(BaseCommand):
    help = "기존 판매관리 HTML .xls 자료를 검증하거나 중복 없이 이관합니다."

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("--start-date", default="2026-06-01")
        parser.add_argument("--end-date", default=str(date.today()))
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--create-products", action="store_true")
        parser.add_argument("--export-json")

    def handle(self, *args, **options):
        start = date.fromisoformat(options["start_date"])
        end = date.fromisoformat(options["end_date"])
        rows = read_legacy_sales(options["source"], start, end)
        if not rows:
            raise CommandError("선택한 기간에 이관할 자료가 없습니다.")
        report = self._report(rows)
        if options.get("export_json"):
            path = Path(options["export_json"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rows, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
        if options["commit"]:
            report.update(self._import(rows, options["create_products"]))
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    def _report(self, rows):
        transactions = defaultdict(list)
        for row in rows:
            transactions[row["legacy_transaction_no"]].append(row)
        return {
            "mode": "commit" if False else "preview",
            "period": [min(x["sale_date"] for x in rows), max(x["sale_date"] for x in rows)],
            "rows": len(rows),
            "transactions": len(transactions),
            "customers_after_normalization": len({x["customer_name"] for x in rows}),
            "models": len({x["model_number"] for x in rows if x["entry_type"] != "payment"}),
            "entry_types": Counter(x["entry_type"] for x in rows),
            "blank_material_rows": sum(not x["material_name"] for x in rows),
            "weightless_rows": sum(x["total_weight"] == 0 for x in rows),
            "decimal_quantity_rows": sum(x["quantity"] != x["quantity"].to_integral_value() for x in rows),
            "mixed_transactions": sum(len({x["entry_type"] for x in items}) > 1 for items in transactions.values()),
        }

    @transaction.atomic
    def _import(self, rows, create_products):
        material_map = {m.name.casefold(): m for m in Material.objects.all()}
        color_map = {c.code.casefold(): c for c in ProductColor.objects.all()}
        suppliers = {}
        for name in sorted({x["purchase_supplier_name"] for x in rows if x["purchase_supplier_name"]}):
            suppliers[name], _ = PurchaseSupplier.objects.get_or_create(name=name)

        latest_by_customer = {}
        for row in rows:
            latest_by_customer[row["customer_name"]] = row
        customers = {}
        for name, latest in latest_by_customer.items():
            customer, _ = Customer.objects.get_or_create(name=name, defaults={"customer_type": "sales", "default_loss_rate": latest["loss_rate"]})
            if customer.default_loss_rate is None:
                customer.default_loss_rate = latest["loss_rate"]
                customer.save(update_fields=["default_loss_rate"])
            customers[name] = customer
        for row in rows:
            if row["customer_original"] != row["customer_name"]:
                CustomerAlias.objects.get_or_create(alias=row["customer_original"], defaults={"customer": customers[row["customer_name"]]})

        products = {p.code.casefold(): p for p in Product.objects.all()}
        if create_products:
            latest_by_model = {}
            meter_models = set()
            for row in rows:
                if row["entry_type"] != "payment" and row["model_number"]:
                    latest_by_model[row["model_number"].casefold()] = row
                    if row["sales_unit"] == "meter":
                        meter_models.add(row["model_number"].casefold())
            for key, row in latest_by_model.items():
                material = material_map.get(row["material_name"].casefold())
                color = color_map.get(row["color_code"].casefold())
                supplier = suppliers.get(row["purchase_supplier_name"])
                product, _ = Product.objects.get_or_create(code=row["model_number"], defaults={
                    "name": row["model_number"], "material": material, "color": color,
                    "default_weight": row["total_weight"] or None, "default_loss_rate": row["loss_rate"],
                    "unit_price": row["unit_labor"], "production_source": row["production_source"],
                    "sales_unit": "meter" if key in meter_models else row["sales_unit"],
                    "weight_required": row["weight_required"], "purchase_supplier": supplier,
                    "default_purchase_loss_rate": row["purchase_loss_rate"],
                    "default_purchase_labor": row["purchase_unit_labor"],
                })
                products[key] = product
                ProductAlias.objects.get_or_create(alias=row["model_number"], defaults={"product": product})

        transactions = {}
        created_transactions = created_items = skipped_items = 0
        for row in rows:
            legacy_no = row["legacy_transaction_no"]
            sale = transactions.get(legacy_no) or SaleTransaction.objects.filter(legacy_transaction_no=legacy_no).first()
            if sale is None:
                candidate = row["transaction_no"]
                if not candidate or SaleTransaction.objects.filter(transaction_no=candidate).exists():
                    seq = DailySaleSequence.objects.filter(sale_date=row["sale_date"]).values_list("last_sequence", flat=True).first() or 0
                    existing = SaleTransaction.objects.filter(sale_date=row["sale_date"]).values_list("transaction_no", flat=True)
                    used = [int(x[-5:]) for x in existing if len(x) == 11 and x[-5:].isdigit()]
                    seq = max([seq, *used]) + 1
                    candidate = f"{row['sale_date']:%y%m%d}{seq:05d}"
                sale = SaleTransaction.objects.create(
                    transaction_no=candidate, legacy_transaction_no=legacy_no,
                    import_source="판매관리.xls", sale_date=row["sale_date"],
                    customer=customers[row["customer_name"]], status="done",
                )
                created_transactions += 1
            transactions[legacy_no] = sale
            existing_item = SaleItem.objects.filter(import_key=row["import_key"]).first()
            if existing_item:
                if existing_item.labor_total_override != row["total_labor"]:
                    existing_item.labor_total_override = row["total_labor"]
                    existing_item.save(update_fields=["labor_total_override"])
                skipped_items += 1
                continue
            material = material_map.get(row["material_name"].casefold())
            color = color_map.get(row["color_code"].casefold())
            product = products.get(row["model_number"].casefold()) if row["entry_type"] != "payment" else None
            SaleItem.objects.bulk_create([SaleItem(
                transaction=sale, entry_type=row["entry_type"], model_number=row["model_number"],
                product=product, material=material, color=color, weight=row["total_weight"],
                settlement_weight=row["settlement_weight"], quantity=row["quantity"],
                sales_unit=row["sales_unit"], loss_rate=row["loss_rate"],
                pure_gold_weight=row["source_pure_gold_weight"], unit_price=row["unit_labor"],
                labor_total_override=row["total_labor"],
                memo=row["memo"], purchase_supplier=suppliers.get(row["purchase_supplier_name"]),
                purchase_loss_rate=row["purchase_loss_rate"], purchase_labor_amount=row["purchase_unit_labor"],
                import_key=row["import_key"],
            )])
            created_items += 1
        for sale in transactions.values():
            sale.refresh_totals()
        for day in {x["sale_date"] for x in rows}:
            max_seq = max(
                [int(no[-5:]) for no in SaleTransaction.objects.filter(sale_date=day).values_list("transaction_no", flat=True) if len(no) == 11 and no[-5:].isdigit()],
                default=0,
            )
            DailySaleSequence.objects.update_or_create(sale_date=day, defaults={"last_sequence": max_seq})
        return {"mode": "commit", "created_transactions": created_transactions, "created_items": created_items, "skipped_items": skipped_items}
