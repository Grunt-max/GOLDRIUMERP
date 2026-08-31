from decimal import Decimal
from datetime import timedelta
import re

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.forms import BaseFormSet, formset_factory
from django.utils import timezone
from .models import CompanyProfile, Customer, DailyActivity, Factory, GoldLedgerEntry, GoldPrice, Material, OpenMarketChannelSetting, OpenMarketProduct, Order, Product, ProductAlias, ProductColor, PurchaseBatch, PurchaseEntry, PurchaseSupplier, SaleItem, SaleTransaction


class OpenMarketProductForm(forms.ModelForm):
    class Meta:
        model = OpenMarketProduct
        fields = ("name", "brand", "model_name", "manufacturer", "origin_country", "category",
                  "default_weight", "base_labor_cost", "target_margin_rate", "naver_fee_rate",
                  "coupang_fee_rate", "description", "detail_page_html", "active")
        widgets = {"description": forms.Textarea(attrs={"rows": 3}),
                   "detail_page_html": forms.Textarea(attrs={"rows": 5})}


class OpenMarketChannelSettingForm(forms.ModelForm):
    class Meta:
        model = OpenMarketChannelSetting
        fields = ("category_code", "channel_product_name", "delivery_method", "delivery_company_code",
                  "outbound_location_code", "return_center_code", "delivery_fee_type", "delivery_fee",
                  "return_fee", "notice_type")


QUICK_ORDER_PATTERN = re.compile(
    r"^\s*(14\s*k|18\s*k|24\s*k|925\s*silver)\s*"
    r"([pgwb]|핑크|옐로우|화이트|베이지)?\s+(.+?)\s+"
    r"(\d+(?:\.\d+)?\s*(?:cm|m))"
    r"(?:\s*(?:[xX*]\s*(\d+)|(\d+)\s*개))?\s*$",
    re.IGNORECASE,
)


def parse_quick_order_lines(raw_text, default_quantity=1):
    parsed, invalid = [], []
    color_names = {"P": "핑크", "G": "옐로우", "W": "화이트", "B": "베이지", "베이지": "베이지"}
    for line_number, source_line in enumerate(raw_text.splitlines(), 1):
        line = source_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("/")]
        order_text = parts[0]
        match = QUICK_ORDER_PATTERN.match(order_text)
        if not match:
            invalid.append(line_number)
            continue
        material_name = re.sub(r"\s+", "", match.group(1)).upper()
        if material_name == "925SILVER":
            material_name = "925 Silver"
        material = Material.objects.filter(name__iexact=material_name, active=True).first()
        if not material:
            invalid.append(line_number)
            continue
        color_code = (match.group(2) or "").upper()
        length_spec = re.sub(r"\s+", "", match.group(4)).upper()
        delivery_type = "finished" if length_spec.endswith("CM") else "semi"
        parsed.append({
            "source_line": line,
            "material": material,
            "color": color_names.get(color_code, match.group(2) or ""),
            "model_number": match.group(3).strip(),
            "length_spec": length_spec,
            "delivery_type": delivery_type,
            "option_detail": " / ".join(part for part in parts[1:] if part) if delivery_type == "finished" else "",
            "quantity": (
                Decimal(re.match(r"\d+(?:\.\d+)?", re.sub(r"\s+", "", match.group(4))).group())
                if not re.sub(r"\s+", "", match.group(4)).upper().endswith("CM")
                else Decimal(match.group(5) or match.group(6) or default_quantity or 1)
            ),
        })
    return parsed, invalid


class StyledForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "field"


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(item, initial) for item in files if item]


class DailyActivityForm(StyledForm):
    images = MultipleFileField(
        label="첨부 사진", required=False,
        widget=MultipleFileInput(attrs={"accept": ".jpg,.jpeg,.png,.webp,.gif"}),
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif"])],
    )

    class Meta:
        model = DailyActivity
        fields = ["activity_date", "content"]
        widgets = {
            "activity_date": forms.DateInput(attrs={"type": "date"}),
            "content": forms.Textarea(attrs={"rows": 2, "placeholder": "오늘 처리한 업무를 입력하세요."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["activity_date"].initial = timezone.localdate()


class FactoryForm(StyledForm):
    class Meta:
        model = Factory
        fields = ["name", "contact", "phone", "memo"]


class GoldPriceForm(StyledForm):
    class Meta:
        model = GoldPrice
        fields = ["market_type", "price_date", "source_price_per_gram", "source_price_per_don", "application_rate", "source_name", "source_url", "is_confirmed", "memo"]
        widgets = {"price_date": forms.DateInput(attrs={"type": "date"})}


class GoldLedgerEntryForm(StyledForm):
    class Meta:
        model = GoldLedgerEntry
        fields = ["entry_date", "entry_type", "destination_type", "purchase_supplier", "material", "actual_weight", "reference_no", "memo", "image"]
        widgets = {"entry_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["entry_date"].initial = timezone.localdate()
        self.fields["entry_type"].choices = [("issue", "금 불출"), ("adjustment", "재고 조정")]
        self.fields["purchase_supplier"].queryset = PurchaseSupplier.objects.filter(active=True)
        self.fields["purchase_supplier"].required = False
        self.fields["material"].queryset = Material.objects.filter(active=True)
        self.fields["material"].required = False
        self.fields["actual_weight"].required = False
        if not self.is_bound:
            material_24k = self.fields["material"].queryset.filter(name__iexact="24K").first()
            if material_24k:
                self.fields["material"].initial = material_24k.pk

    def clean(self):
        cleaned = super().clean()
        entry_type = cleaned.get("entry_type")
        if entry_type == "issue" and cleaned.get("destination_type") == "purchase_supplier" and not cleaned.get("purchase_supplier"):
            self.add_error("purchase_supplier", "금이 전달될 매입처를 선택하세요.")
        if not cleaned.get("material"):
            self.add_error("material", "재질을 선택하세요.")
        if cleaned.get("actual_weight") is None:
            self.add_error("actual_weight", "중량을 입력하세요.")
        return cleaned


class PurchaseSupplierForm(StyledForm):
    class Meta:
        model = PurchaseSupplier
        fields = ["name", "contact", "phone", "default_loss_rate", "memo"]
        widgets = {"default_loss_rate": forms.NumberInput(attrs={"min": "0", "step": "0.01", "placeholder": "매입처 기본 해리율"})}


class PurchaseEntryForm(StyledForm):
    class Meta:
        model = PurchaseEntry
        fields = ["purchase_date", "supplier", "material", "actual_weight", "loss_rate", "purchase_amount", "reference_no", "memo", "image"]
        widgets = {"purchase_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["purchase_date"].initial = timezone.localdate()
        self.fields["supplier"].queryset = PurchaseSupplier.objects.filter(active=True)
        self.fields["material"].queryset = Material.objects.filter(active=True)
        self.fields["loss_rate"].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("loss_rate") is None:
            supplier, material = cleaned.get("supplier"), cleaned.get("material")
            cleaned["loss_rate"] = supplier.default_loss_rate if supplier and supplier.default_loss_rate is not None else material.default_loss_rate if material else Decimal("0")
        return cleaned


class PurchaseHeaderForm(forms.Form):
    purchase_date = forms.DateField(label="매입일", widget=forms.DateInput(attrs={"type": "date", "class": "field"}))
    supplier = forms.ModelChoiceField(label="매입처", queryset=PurchaseSupplier.objects.none(), widget=forms.Select(attrs={"class": "field"}))
    reference_no = forms.CharField(label="매입번호", max_length=30, required=False, widget=forms.TextInput(attrs={"class": "field", "placeholder": "비우면 자동 발급"}))
    image = forms.FileField(label="전표", required=False, validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif", "pdf"])], widget=forms.ClearableFileInput(attrs={"class": "field", "accept": ".jpg,.jpeg,.png,.webp,.gif,.pdf"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = PurchaseSupplier.objects.filter(active=True)
        if not self.is_bound:
            self.fields["purchase_date"].initial = timezone.localdate()

    def clean_reference_no(self):
        value = self.cleaned_data.get("reference_no", "").strip()
        if value and PurchaseBatch.objects.filter(reference_no=value).exists():
            raise ValidationError("이미 사용 중인 매입번호입니다.")
        return value


class PurchaseLineForm(StyledForm):
    class Meta:
        model = PurchaseEntry
        fields = ["item_name", "material", "actual_weight", "loss_rate", "purchase_amount", "memo"]
        widgets = {
            "actual_weight": forms.NumberInput(attrs={"min": "0", "step": "0.001"}),
            "loss_rate": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "purchase_amount": forms.NumberInput(attrs={"min": "0", "step": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item_name"].required = False
        self.fields["material"].queryset = Material.objects.filter(active=True)
        self.fields["material"].required = False
        self.fields["actual_weight"].required = False
        self.fields["loss_rate"].required = False
        self.fields["purchase_amount"].required = False


class BasePurchaseLineFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active = []
        for form in self.forms:
            data = form.cleaned_data
            if data.get("DELETE"):
                continue
            if data.get("item_name") or data.get("material") or data.get("actual_weight"):
                active.append(form)
                if not data.get("item_name"):
                    form.add_error("item_name", "매입 품목명을 입력하세요.")
                if not data.get("material"):
                    form.add_error("material", "재질을 선택하세요.")
                if not data.get("actual_weight") or data["actual_weight"] <= 0:
                    form.add_error("actual_weight", "0보다 큰 중량을 입력하세요.")
        if not active:
            raise ValidationError("아무것도 입력되지 않았습니다.")


PurchaseLineFormSet = formset_factory(PurchaseLineForm, formset=BasePurchaseLineFormSet, extra=5, can_delete=True)


class CustomerForm(StyledForm):
    class Meta:
        model = Customer
        fields = ["name", "customer_type", "contact", "phone", "default_loss_rate", "supplier_name_override", "memo"]
        widgets = {
            "default_loss_rate": forms.NumberInput(attrs={"min": "0", "step": "0.01", "placeholder": "미설정 시 재질 기본값 적용"}),
            "supplier_name_override": forms.TextInput(attrs={"placeholder": "비워두면 기초관리의 기본 공급자명 사용"}),
        }


class ProductForm(StyledForm):
    class Meta:
        model = Product
        fields = [
            "name", "code", "image", "unit_price", "production_source", "sales_unit",
            "weight_required", "purchase_supplier",
            "default_purchase_loss_rate", "default_purchase_labor", "stock_quantity", "active",
        ]


class MaterialForm(StyledForm):
    class Meta:
        model = Material
        fields = ["name", "purity_rate", "default_loss_rate", "apply_loss_rate", "active"]


class ProductColorForm(StyledForm):
    class Meta:
        model = ProductColor
        fields = ["code", "name", "active"]


class CompanyProfileForm(StyledForm):
    weight_decimal_places = forms.TypedChoiceField(
        label="중량 표시 소수점",
        choices=CompanyProfile.WEIGHT_DECIMAL_CHOICES,
        coerce=int,
        required=False,
        help_text="다음 자리에서 반올림하며 최대 3자리까지 설정할 수 있습니다.",
    )

    class Meta:
        model = CompanyProfile
        fields = ["supplier_name", "supplier_phone", "weight_decimal_places"]

    def clean_weight_decimal_places(self):
        value = self.cleaned_data.get("weight_decimal_places")
        return value if value is not None else (self.instance.weight_decimal_places or 2)


class OrderForm(StyledForm):
    class Meta:
        model = Order
        fields = [
            "source_type", "ordered_at", "due_date", "customer", "model_number",
            "raw_order_text", "order_image", "material", "color", "delivery_type",
            "length_spec", "option_detail", "quantity", "status", "memo",
        ]
        widgets = {
            "ordered_at": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "model_number": forms.TextInput(attrs={"autocomplete": "off", "list": "model-suggestions", "placeholder": "사진주문·단일주문 모델번호"}),
            "raw_order_text": forms.Textarea(attrs={"rows": 4, "placeholder": "한 줄에 제품 하나씩 입력\n14kp 1.3mm로프 5M\n18kp 1.3mm로프 5M"}),
            "length_spec": forms.TextInput(attrs={"placeholder": "예: 42cm 또는 1M/2M"}),
            "option_detail": forms.TextInput(attrs={"placeholder": "예: 붕어장식, 연장고리 없음"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["ordered_at"].initial = timezone.localdate()
            self.fields["due_date"].initial = timezone.localdate() + timedelta(days=7)
        self.fields["customer"].queryset = Customer.objects.filter(customer_type="sales")
        self.fields["material"].queryset = Material.objects.filter(active=True)
        self.fields["quantity"].label = "수량(완제품) / 길이M(반제품)"
        for name in ("customer", "model_number", "ordered_at"):
            self.fields[name].required = True
        self.fields["model_number"].required = False

    def clean(self):
        cleaned = super().clean()
        customer = cleaned.get("customer")
        quantity = cleaned.get("quantity")
        ordered_at = cleaned.get("ordered_at")
        if ordered_at and not cleaned.get("due_date"):
            cleaned["due_date"] = ordered_at + timedelta(days=7)
        model_number = (cleaned.get("model_number") or "").strip()
        product = Product.objects.filter(code__iexact=model_number, active=True).first()
        if product:
            cleaned["product"] = product
        else:
            cleaned["product"] = None
        raw = cleaned.get("raw_order_text") or ""
        source_type = cleaned.get("source_type")
        if source_type == "quick" and raw.strip():
            parsed_lines, invalid_lines = parse_quick_order_lines(raw, quantity or 1)
            if invalid_lines:
                self.add_error("raw_order_text", f"해석할 수 없는 주문이 있습니다: {', '.join(map(str, invalid_lines))}번째 줄")
            cleaned["parsed_lines"] = parsed_lines
        else:
            cleaned["parsed_lines"] = []
        if not model_number and not cleaned["parsed_lines"]:
            self.add_error("model_number", "모델번호를 입력하거나 빠른 주문 원문을 입력하세요.")
        if not cleaned.get("material"):
            material_match = re.search(r"(?i)(14\s*k|18\s*k|24\s*k|925\s*silver)", raw)
            if material_match:
                material_name = re.sub(r"\s+", "", material_match.group(1)).upper()
                if material_name == "925SILVER":
                    material_name = "925 Silver"
                cleaned["material"] = Material.objects.filter(name__iexact=material_name, active=True).first()
        if not cleaned.get("length_spec"):
            length_match = re.search(r"(?i)\b\d+(?:\.\d+)?\s*(?:cm|m)(?:\s*/\s*\d+(?:\.\d+)?\s*m)?\b", raw)
            if length_match:
                cleaned["length_spec"] = length_match.group(0).replace(" ", "")
        if not cleaned.get("color"):
            color_match = re.search(r"(?i)(?:^|\s)(P|G|W|핑크|옐로우|화이트)(?:\s|$)", raw)
            if color_match:
                cleaned["color"] = {"P": "핑크", "G": "옐로우", "W": "화이트"}.get(color_match.group(1).upper(), color_match.group(1))
        if customer and customer.customer_type != "sales":
            self.add_error("customer", "판매처만 선택할 수 있습니다.")
        if quantity is not None and quantity <= 0:
            self.add_error("quantity", "주문량은 0보다 커야 합니다.")
        if cleaned.get("delivery_type") == "finished" and quantity is not None and quantity != quantity.to_integral_value():
            self.add_error("quantity", "완제품 수량은 정수로 입력하세요.")
        if cleaned.get("delivery_type") == "semi" and cleaned.get("length_spec"):
            meter_match = re.fullmatch(r"(?i)\s*(\d+(?:\.\d+)?)\s*m\s*", cleaned["length_spec"])
            if meter_match:
                cleaned["quantity"] = Decimal(meter_match.group(1))
        return cleaned

    def save(self, commit=True):
        order = super().save(commit=False)
        order.product = self.cleaned_data.get("product")
        if order.product:
            order.weight = order.product.default_weight or 0
            order.unit_price = order.product.unit_price
        else:
            order.weight = 0
            order.unit_price = 0
        if commit:
            order.save()
        return order


class SaleHeaderForm(forms.Form):
    customer = forms.ModelChoiceField(label="거래처", queryset=Customer.objects.none())
    ordered_at = forms.DateField(label="거래일", widget=forms.DateInput(attrs={"type": "date"}), initial=timezone.localdate)
    status = forms.ChoiceField(label="상태", choices=SaleTransaction.STATUS_CHOICES, initial="new", widget=forms.HiddenInput())
    memo = forms.CharField(label="거래 비고", required=False, widget=forms.TextInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(customer_type="sales")
        for field in self.fields.values():
            field.widget.attrs["class"] = "field"


class MoneyDecimalField(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(",", "").replace("₩", "").strip()
        return super().to_python(value)


class SaleLineForm(forms.Form):
    entry_type = forms.ChoiceField(
        label="구분",
        choices=(("sale", "판매"), ("return", "반품"), ("payment", "결제")),
        initial="sale",
    )
    model_number = forms.CharField(label="모델번호", max_length=40, required=False, widget=forms.TextInput(attrs={"autocomplete": "off"}))
    material = forms.ModelChoiceField(label="재질", queryset=Material.objects.none(), required=False)
    color = forms.ModelChoiceField(label="색상", queryset=ProductColor.objects.none(), required=False)
    weight = forms.DecimalField(label="총중량(g)", max_digits=10, decimal_places=3, required=False, min_value=0)
    settlement_weight = forms.DecimalField(label="정산중량(g)", max_digits=10, decimal_places=3, required=False, min_value=0)
    loss_rate = forms.DecimalField(label="해리율(%)", max_digits=6, decimal_places=2, required=False)
    quantity = forms.DecimalField(
        label="수량", max_digits=12, decimal_places=2, min_value=Decimal("0.01"),
        required=False, initial=1, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}),
    )
    unit_price = MoneyDecimalField(label="공임", max_digits=12, decimal_places=0, required=False, min_value=0, initial=0, widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}))
    memo = forms.CharField(label="비고", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["material"].queryset = Material.objects.filter(active=True)
        self.fields["color"].queryset = ProductColor.objects.filter(active=True)
        for field in self.fields.values():
            field.widget.attrs["class"] = "field"

    def clean(self):
        cleaned = super().clean()
        model_number = (cleaned.get("model_number") or "").strip()
        entry_type = cleaned.get("entry_type") or "sale"
        if entry_type == "payment":
            cleaned["model_number"] = "결제"
            model_number = "결제"
            cleaned["catalog_product"] = None
            cleaned["material"] = Material.objects.filter(name__iexact="24K", active=True).first()
            cleaned["color"] = None
            cleaned["loss_rate"] = Decimal("0")
            cleaned["quantity"] = 1
            if cleaned["material"] is None:
                self.add_error("material", "기초관리에서 활성 상태의 24K 재질을 등록하세요.")
        if not model_number:
            return cleaned
        product = None if entry_type == "payment" else Product.objects.filter(code__iexact=model_number, active=True).first()
        if product is None and entry_type != "payment":
            alias = ProductAlias.objects.select_related("product").filter(alias__iexact=model_number, product__active=True).first()
            product = alias.product if alias else None
        cleaned["catalog_product"] = product
        if product:
            cleaned["unit_price"] = cleaned.get("unit_price") or product.unit_price
        weight_required = not product or product.weight_required
        if cleaned.get("material") and cleaned["material"].name.lower() == "925 silver" and not product:
            weight_required = False
        required_fields = [("material", "재질을 선택하세요."), ("unit_price", "단가를 입력하세요."), ("quantity", "수량을 입력하세요.")]
        if weight_required:
            required_fields.append(("weight", "중량을 입력하세요."))
        elif cleaned.get("weight") is None:
            cleaned["weight"] = Decimal("0")
        for field, message in required_fields:
            if cleaned.get(field) is None:
                self.add_error(field, message)
        return cleaned


class BaseSaleLineFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        entered_lines = [
            form for form in self.forms
            if not form.cleaned_data.get("DELETE") and form.cleaned_data.get("model_number")
        ]
        if not entered_lines:
            raise ValidationError("아무것도 입력되지 않았습니다. 주문 등록 실패")


SaleLineFormSet = formset_factory(
    SaleLineForm, formset=BaseSaleLineFormSet,
    extra=5, min_num=0, validate_min=False, can_delete=True,
)
