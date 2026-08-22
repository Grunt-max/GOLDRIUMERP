import re
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("th", "td") and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def decimal_value(value, default=None):
    value = str(value or "").replace(",", "").strip()
    if not value:
        return default
    try:
        return Decimal(value)
    except InvalidOperation:
        return default


def percent_from_multiplier(value):
    multiplier = decimal_value(value)
    if multiplier is None:
        return None
    return ((multiplier - Decimal("1")) * Decimal("100")).quantize(Decimal("0.01"))


def normalize_customer_name(name):
    original = name.strip()
    base = re.sub(r"_?판매_?\d+(?:\.\d+)?프로$", "", original)
    base = re.sub(r"_?\d+(?:\.\d+)?프로$", "", base)
    return base.rstrip("_ ") or original


def convert_transaction_no(legacy_no):
    legacy_no = legacy_no.lstrip("'").strip()
    if re.fullmatch(r"\d{12}", legacy_no):
        return f"{legacy_no[2:8]}{int(legacy_no[-4:]):05d}"
    return ""


def normalize_material(value):
    value = value.strip()
    return {"실버": "925 Silver"}.get(value, value)


def read_legacy_sales(path, start_date, end_date):
    parser = _TableParser()
    parser.feed(Path(path).read_text(encoding="utf-8"))
    rows = [row for row in parser.rows if len(row) == 42]
    if rows and rows[0][0] == "No":
        rows = rows[1:]
    normalized = []
    for row in rows:
        sale_date = date.fromisoformat(row[3])
        if not start_date <= sale_date <= end_date:
            continue
        legacy_no = row[10].lstrip("'").strip()
        quantity = decimal_value(row[33], Decimal("1"))
        total_labor = decimal_value(row[34], Decimal("0"))
        unit_labor = decimal_value(row[29])
        if unit_labor is None:
            unit_labor = total_labor / quantity if quantity else Decimal("0")
        total_weight = decimal_value(row[23], Decimal("0"))
        metal_weight = decimal_value(row[24])
        source_pure = decimal_value(row[26], Decimal("0"))
        purchase_supplier = row[37].strip()
        entry_type = {"판매": "sale", "반품": "return", "결제": "payment", "WG": "wg", "DC": "dc", "VD": "vd"}.get(row[11], "sale")
        normalized.append({
            "source_row_no": int(row[0]),
            "import_key": f"legacy-sales:{row[0]}",
            "sale_date": sale_date,
            "legacy_transaction_no": legacy_no,
            "transaction_no": convert_transaction_no(legacy_no),
            "customer_original": row[9].strip(),
            "customer_name": normalize_customer_name(row[9]),
            "entry_type": entry_type,
            "model_number": row[14].strip(),
            "material_name": normalize_material(row[16]),
            "color_code": row[17].strip(),
            "total_weight": total_weight,
            "settlement_weight": metal_weight if metal_weight is not None and metal_weight != total_weight else None,
            "source_pure_gold_weight": source_pure,
            "loss_rate": percent_from_multiplier(row[8]) or Decimal("0"),
            "quantity": quantity,
            "sales_unit": "meter" if quantity != quantity.to_integral_value() else "piece",
            "unit_labor": unit_labor,
            "total_labor": total_labor,
            "memo": row[21].strip(),
            "purchase_supplier_name": "" if purchase_supplier in ("", "NONE", "공장") else purchase_supplier,
            "production_source": "external" if purchase_supplier not in ("", "NONE", "공장") else "own",
            "purchase_loss_rate": percent_from_multiplier(row[38]),
            "purchase_unit_labor": decimal_value(row[39], Decimal("0")),
            "purchase_total_labor": decimal_value(row[41], Decimal("0")),
            "size": row[20].strip(),
            "receipt_no": row[13].strip(),
        })
    meter_models = {row["model_number"].casefold() for row in normalized if row["sales_unit"] == "meter"}
    for row in normalized:
        if row["model_number"].casefold() in meter_models:
            row["sales_unit"] = "meter"
        if row["material_name"] in ("", "925 Silver") and row["total_weight"] == 0:
            row["weight_required"] = False
        else:
            row["weight_required"] = True
    return normalized

