from django.db import models, transaction as db_transaction
from django.conf import settings
from django.core.validators import FileExtensionValidator
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from django.utils import timezone


def generate_transaction_no(sale_date=None):
    sale_date = sale_date or timezone.localdate()
    with db_transaction.atomic():
        sequence, _ = DailySaleSequence.objects.select_for_update().get_or_create(
            sale_date=sale_date, defaults={"last_sequence": 0}
        )
        if sequence.last_sequence >= 99999:
            raise ValueError("해당 거래일의 거래번호가 99999번을 초과했습니다.")
        sequence.last_sequence += 1
        sequence.save(update_fields=["last_sequence"])
    return f"{sale_date:%y%m%d}{sequence.last_sequence:05d}"


def generate_order_no(ordered_at=None):
    ordered_at = ordered_at or timezone.localdate()
    with db_transaction.atomic():
        sequence, _ = DailyOrderSequence.objects.select_for_update().get_or_create(
            order_date=ordered_at, defaults={"last_sequence": 0}
        )
        if sequence.last_sequence >= 999:
            raise ValueError("해당 주문일의 주문번호가 999번을 초과했습니다.")
        sequence.last_sequence += 1
        sequence.save(update_fields=["last_sequence"])
    return f"{ordered_at:%y%m%d}{sequence.last_sequence:03d}"


class Customer(models.Model):
    TYPE_CHOICES = [("sales", "판매처"), ("purchase", "매입처")]
    name = models.CharField("거래처명", max_length=100)
    customer_type = models.CharField("구분", max_length=10, choices=TYPE_CHOICES, default="sales")
    contact = models.CharField("담당자", max_length=50, blank=True)
    phone = models.CharField("연락처", max_length=30, blank=True)
    memo = models.TextField("메모", blank=True)
    default_loss_rate = models.DecimalField("기본 해리율(%)", max_digits=6, decimal_places=2, null=True, blank=True)
    supplier_name_override = models.CharField("명세서 공급자명", max_length=100, blank=True)
    created_at = models.DateTimeField("등록일", auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CustomerAlias(models.Model):
    customer = models.ForeignKey(Customer, verbose_name="거래처", on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField("과거 거래처명/별칭", max_length=100, unique=True)

    class Meta:
        ordering = ["alias"]

    def __str__(self):
        return f"{self.alias} → {self.customer.name}"


class Material(models.Model):
    name = models.CharField("재질명", max_length=30, unique=True)
    purity_rate = models.DecimalField("순도", max_digits=6, decimal_places=4, default=1)
    default_loss_rate = models.DecimalField("기본 해리율(%)", max_digits=6, decimal_places=2, default=0)
    apply_loss_rate = models.BooleanField("해리율 적용", default=True)
    active = models.BooleanField("사용", default=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class ProductColor(models.Model):
    code = models.CharField("색상코드", max_length=10, unique=True)
    name = models.CharField("색상명", max_length=30)
    active = models.BooleanField("사용", default=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.code} ({self.name})"


class CompanyProfile(models.Model):
    WEIGHT_DECIMAL_CHOICES = [(value, f"{value}자리") for value in range(4)]

    singleton_key = models.CharField(max_length=20, unique=True, default="default", editable=False)
    supplier_name = models.CharField("공급자명", max_length=100, default="골드리움")
    supplier_phone = models.CharField("공급자 전화번호", max_length=30, blank=True)
    weight_decimal_places = models.PositiveSmallIntegerField(
        "중량 표시 소수점",
        choices=WEIGHT_DECIMAL_CHOICES,
        default=2,
        help_text="판매관리와 각 현황표의 중량을 표시할 자릿수입니다. 다음 자리에서 반올림합니다.",
    )

    class Meta:
        verbose_name = "회사 기본정보"
        verbose_name_plural = "회사 기본정보"

    def __str__(self):
        return self.supplier_name


class Product(models.Model):
    PRODUCTION_SOURCE_CHOICES = [("own", "우리 공장"), ("external", "외부 매입")]
    SALES_UNIT_CHOICES = [("piece", "개"), ("meter", "M"), ("gram", "g")]

    name = models.CharField("상품명", max_length=120)
    code = models.CharField("모델번호", max_length=40, unique=True)
    material = models.ForeignKey(Material, verbose_name="기본 재질", on_delete=models.PROTECT, null=True, blank=True)
    color = models.ForeignKey(ProductColor, verbose_name="기본 색상", on_delete=models.PROTECT, null=True, blank=True)
    default_weight = models.DecimalField("기본 중량(g)", max_digits=10, decimal_places=3, null=True, blank=True)
    default_loss_rate = models.DecimalField("제품 해리율(%)", max_digits=6, decimal_places=2, null=True, blank=True)
    unit_price = models.DecimalField("판매단가", max_digits=12, decimal_places=0)
    production_source = models.CharField("생산 구분", max_length=10, choices=PRODUCTION_SOURCE_CHOICES, default="own")
    sales_unit = models.CharField("판매 단위", max_length=10, choices=SALES_UNIT_CHOICES, default="piece")
    weight_required = models.BooleanField("중량 정산", default=True)
    purchase_supplier = models.ForeignKey(
        "PurchaseSupplier", verbose_name="기본 매입처", on_delete=models.PROTECT,
        null=True, blank=True, related_name="catalog_products",
    )
    default_purchase_loss_rate = models.DecimalField("기본 매입 해리율(%)", max_digits=6, decimal_places=2, null=True, blank=True)
    default_purchase_labor = models.DecimalField("기본 매입 공임", max_digits=14, decimal_places=0, default=0)
    stock_quantity = models.PositiveIntegerField("현재 재고", default=0)
    active = models.BooleanField("판매중", default=True)
    is_deleted = models.BooleanField("삭제", default=False, db_index=True)
    deleted_at = models.DateTimeField("삭제일시", null=True, blank=True)
    image = models.FileField(
        "상품사진", upload_to="products/", blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif"])],
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class ProductAlias(models.Model):
    product = models.ForeignKey(Product, verbose_name="상품", on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField("모델번호 별칭", max_length=80, unique=True)

    class Meta:
        ordering = ["alias"]

    def __str__(self):
        return f"{self.alias} → {self.product.code}"


class ProductWeightProfile(models.Model):
    """Historical unit-weight averages for a product/material/color combination."""

    product = models.ForeignKey(Product, verbose_name="상품", on_delete=models.CASCADE, related_name="weight_profiles")
    material = models.ForeignKey(Material, verbose_name="재질", on_delete=models.PROTECT)
    color = models.ForeignKey(ProductColor, verbose_name="색상", on_delete=models.PROTECT, null=True, blank=True)
    sale_average_weight = models.DecimalField("판매 평균중량", max_digits=12, decimal_places=3, null=True, blank=True)
    sale_sample_count = models.PositiveIntegerField("판매 표본수", default=0)
    purchase_average_weight = models.DecimalField("매입 평균중량", max_digits=12, decimal_places=3, null=True, blank=True)
    purchase_sample_count = models.PositiveIntegerField("매입 표본수", default=0)
    average_weight = models.DecimalField("추천 평균중량", max_digits=12, decimal_places=3)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__code", "material__name", "color__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "material", "color"],
                condition=models.Q(color__isnull=False),
                name="unique_product_weight_profile_color",
            ),
            models.UniqueConstraint(
                fields=["product", "material"],
                condition=models.Q(color__isnull=True),
                name="unique_product_weight_profile_no_color",
            ),
        ]

    def __str__(self):
        color = self.color.code if self.color else "-"
        return f"{self.product.code} / {self.material.name} / {color}: {self.average_weight}g"


class Order(models.Model):
    STATUS_CHOICES = [("new", "접수"), ("partial", "부분출고"), ("done", "완료"), ("cancel", "취소")]
    SOURCE_CHOICES = [("legacy", "기존자료"), ("quick", "빠른주문"), ("photo", "사진주문")]
    DELIVERY_CHOICES = [("finished", "완제품"), ("semi", "반제품")]
    customer = models.ForeignKey(Customer, verbose_name="거래처", on_delete=models.PROTECT)
    product = models.ForeignKey(Product, verbose_name="카탈로그 상품", on_delete=models.PROTECT, null=True, blank=True)
    transaction_no = models.CharField("거래번호", max_length=30, db_index=True, blank=True)
    model_number = models.CharField("모델번호", max_length=40, default="")
    material = models.ForeignKey(Material, verbose_name="재질", on_delete=models.PROTECT, null=True, blank=True)
    weight = models.DecimalField("개당 중량(g)", max_digits=10, decimal_places=3, default=0)
    loss_rate = models.DecimalField("해리율(%)", max_digits=6, decimal_places=2, default=0)
    pure_gold_weight = models.DecimalField("순금 환산중량(g)", max_digits=12, decimal_places=3, default=0)
    quantity = models.DecimalField("주문량", max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField("판매단가", max_digits=12, decimal_places=0)
    paid_amount = models.DecimalField("입금액", max_digits=12, decimal_places=0, default=0)
    labor_amount = models.DecimalField("공임", max_digits=12, decimal_places=0, default=0)
    paid_labor_amount = models.DecimalField("공임 입금액", max_digits=12, decimal_places=0, default=0)
    status = models.CharField("상태", max_length=10, choices=STATUS_CHOICES, default="new")
    ordered_at = models.DateField("주문일")
    due_date = models.DateField("정상 납기일", null=True, blank=True, db_index=True)
    completed_at = models.DateField("완료일", null=True, blank=True, db_index=True)
    source_type = models.CharField("접수 방식", max_length=10, choices=SOURCE_CHOICES, default="quick")
    order_image = models.FileField(
        "주문 사진", upload_to="orders/%Y/%m/", blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif"])],
    )
    raw_order_text = models.TextField("빠른 주문 원문", blank=True)
    delivery_type = models.CharField("납품 형태", max_length=10, choices=DELIVERY_CHOICES, default="finished")
    color = models.CharField("색상", max_length=20, blank=True)
    thickness_spec = models.CharField("굵기", max_length=40, blank=True)
    length_spec = models.CharField("길이", max_length=40, blank=True)
    option_detail = models.CharField("장식·옵션", max_length=200, blank=True)
    fulfilled_quantity = models.DecimalField("출고량", max_digits=10, decimal_places=2, default=0)
    memo = models.TextField("메모", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField("삭제 여부", default=False, db_index=True)
    deleted_at = models.DateTimeField("삭제일시", null=True, blank=True)

    class Meta:
        ordering = ["-ordered_at", "-id"]

    @property
    def total_amount(self):
        return self.quantity * self.unit_price

    @property
    def unpaid_amount(self):
        return self.total_amount - self.paid_amount

    @property
    def unpaid_labor_amount(self):
        return self.labor_amount - self.paid_labor_amount

    @property
    def total_weight(self):
        return Decimal(str(self.weight or 0)) * Decimal(str(self.quantity or 0))

    @property
    def remaining_quantity(self):
        return max(self.quantity - self.fulfilled_quantity, Decimal("0"))

    @property
    def order_unit(self):
        return "M" if self.delivery_type == "semi" else "개"

    def calculate_pure_gold_weight(self):
        total = self.total_weight
        if not self.material or not self.material.apply_loss_rate:
            return total.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        multiplier = self.material.purity_rate * (Decimal("1") + self.loss_rate / Decimal("100"))
        return (total * multiplier).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    def save(self, *args, **kwargs):
        if not self.transaction_no:
            self.transaction_no = generate_order_no(self.ordered_at)
        if not self.due_date and self.ordered_at:
            self.due_date = self.ordered_at + timedelta(days=7)
        if self.product_id and not self.model_number:
            self.model_number = self.product.code
        self.pure_gold_weight = self.calculate_pure_gold_weight()
        if self.status != "done":
            self.completed_at = None
        super().save(*args, **kwargs)


class DailySaleSequence(models.Model):
    sale_date = models.DateField("거래일", unique=True)
    last_sequence = models.PositiveIntegerField("마지막 순번", default=0)

    class Meta:
        ordering = ["-sale_date"]

    def __str__(self):
        return f"{self.sale_date}: {self.last_sequence:05d}"


class DailyOrderSequence(models.Model):
    order_date = models.DateField("주문일", unique=True)
    last_sequence = models.PositiveIntegerField("마지막 순번", default=0)

    class Meta:
        ordering = ["-order_date"]

    def __str__(self):
        return f"{self.order_date}: {self.last_sequence:03d}"


class DailyActivity(models.Model):
    activity_date = models.DateField("행적일", default=timezone.localdate, db_index=True)
    content = models.TextField("업무 내용", max_length=1000)
    image = models.FileField(
        "첨부 사진", upload_to="activities/%Y/%m/", blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif"])],
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="작성자", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="erp_daily_activities",
    )
    created_at = models.DateTimeField("작성일시", auto_now_add=True)
    is_deleted = models.BooleanField("삭제 여부", default=False, db_index=True)
    deleted_at = models.DateTimeField("삭제일시", null=True, blank=True)

    class Meta:
        ordering = ["-activity_date", "-created_at"]

    def __str__(self):
        return f"{self.activity_date}: {self.content[:30]}"

    @property
    def photo_count(self):
        return (1 if self.image else 0) + len(self.photos.all())


class DailyActivityPhoto(models.Model):
    activity = models.ForeignKey(DailyActivity, on_delete=models.CASCADE, related_name="photos", verbose_name="당일행적")
    image = models.FileField(
        "사진", upload_to="activities/%Y/%m/",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif"])],
    )
    uploaded_at = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        ordering = ["id"]


class Factory(models.Model):
    name = models.CharField("공장명", max_length=100, unique=True)
    contact = models.CharField("담당자", max_length=50, blank=True)
    phone = models.CharField("연락처", max_length=30, blank=True)
    memo = models.CharField("비고", max_length=200, blank=True)
    active = models.BooleanField("사용", default=True)
    created_at = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class GoldLedgerEntry(models.Model):
    TYPE_CHOICES = [
        ("issue", "금 불출"), ("receive", "금 회수"),
        ("gold_payment", "금 결제"), ("cash_payment", "현금 결제"),
        ("adjustment", "조정"),
    ]
    DESTINATION_CHOICES = [("own_factory", "우리공장"), ("purchase_supplier", "매입처")]
    entry_date = models.DateField("수불일", default=timezone.localdate, db_index=True)
    factory = models.ForeignKey(Factory, verbose_name="공장", on_delete=models.PROTECT, related_name="ledger_entries")
    destination_type = models.CharField("불출 목적지", max_length=20, choices=DESTINATION_CHOICES, default="own_factory")
    purchase_supplier = models.ForeignKey(
        "PurchaseSupplier", verbose_name="매입처", on_delete=models.PROTECT,
        null=True, blank=True, related_name="gold_ledger_entries",
    )
    entry_type = models.CharField("수불 구분", max_length=20, choices=TYPE_CHOICES, db_index=True)
    material = models.ForeignKey(Material, verbose_name="재질", on_delete=models.PROTECT, null=True, blank=True)
    actual_weight = models.DecimalField("실제 중량(g)", max_digits=12, decimal_places=3, default=0)
    pure_gold_weight = models.DecimalField("순금 환산중량(g)", max_digits=14, decimal_places=3, default=0)
    cash_amount = models.DecimalField("현금 결제액", max_digits=14, decimal_places=0, default=0)
    reference_no = models.CharField("관련번호", max_length=30, blank=True)
    memo = models.CharField("비고", max_length=200, blank=True)
    is_closing_transfer = models.BooleanField("전량 불출 마감", default=False, db_index=True)
    image = models.FileField("전표 사진", upload_to="gold-ledger/%Y/%m/", blank=True, validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif", "pdf"])])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="작성자", null=True, blank=True, on_delete=models.SET_NULL)
    is_deleted = models.BooleanField("삭제 여부", default=False, db_index=True)
    deleted_at = models.DateTimeField("삭제일시", null=True, blank=True)
    created_at = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        ordering = ["-entry_date", "-id"]

    @property
    def gold_balance_effect(self):
        if self.entry_type == "issue":
            return -self.pure_gold_weight
        if self.entry_type in ("receive", "gold_payment"):
            return self.pure_gold_weight
        if self.entry_type == "adjustment":
            return self.pure_gold_weight
        return Decimal("0")

    def save(self, *args, **kwargs):
        if self.entry_type == "cash_payment":
            self.material = None
            self.actual_weight = Decimal("0")
            self.pure_gold_weight = Decimal("0")
        elif self.material:
            self.pure_gold_weight = (self.actual_weight * self.material.purity_rate).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)


class PurchaseSupplier(models.Model):
    name = models.CharField("매입처명", max_length=100, unique=True)
    contact = models.CharField("담당자", max_length=50, blank=True)
    phone = models.CharField("연락처", max_length=30, blank=True)
    default_loss_rate = models.DecimalField("기본 해리율(%)", max_digits=6, decimal_places=2, null=True, blank=True)
    memo = models.CharField("비고", max_length=200, blank=True)
    active = models.BooleanField("사용", default=True)
    created_at = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PurchaseBatch(models.Model):
    purchase_date = models.DateField("매입일", default=timezone.localdate, db_index=True)
    supplier = models.ForeignKey(PurchaseSupplier, verbose_name="매입처", on_delete=models.PROTECT, related_name="purchase_batches")
    reference_no = models.CharField("매입번호", max_length=30, unique=True)
    image = models.FileField("전표", upload_to="purchases/%Y/%m/", blank=True, validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif", "pdf"])])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="작성자", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        ordering = ["-purchase_date", "-id"]

    def __str__(self):
        return self.reference_no


class PurchaseEntry(models.Model):
    batch = models.ForeignKey(PurchaseBatch, verbose_name="매입 헤더", on_delete=models.PROTECT, related_name="items", null=True, blank=True)
    purchase_date = models.DateField("매입일", default=timezone.localdate, db_index=True)
    supplier = models.ForeignKey(PurchaseSupplier, verbose_name="매입처", on_delete=models.PROTECT, related_name="purchases")
    material = models.ForeignKey(Material, verbose_name="재질", on_delete=models.PROTECT)
    item_name = models.CharField("매입 품목명", max_length=100, default="")
    actual_weight = models.DecimalField("매입 중량(g)", max_digits=12, decimal_places=3)
    loss_rate = models.DecimalField("해리율(%)", max_digits=6, decimal_places=2, default=0)
    pure_gold_weight = models.DecimalField("순금 환산중량(g)", max_digits=14, decimal_places=3, default=0)
    purchase_amount = models.DecimalField("매입 공임(원)", max_digits=14, decimal_places=0, default=0)
    reference_no = models.CharField("매입번호", max_length=30, blank=True)
    memo = models.CharField("비고", max_length=200, blank=True)
    image = models.FileField("매입 전표", upload_to="purchases/%Y/%m/", blank=True, validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif", "pdf"])])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="작성자", null=True, blank=True, on_delete=models.SET_NULL)
    is_deleted = models.BooleanField("삭제 여부", default=False, db_index=True)
    deleted_at = models.DateTimeField("삭제일시", null=True, blank=True)
    created_at = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        ordering = ["-purchase_date", "-id"]

    def save(self, *args, **kwargs):
        multiplier = self.material.purity_rate
        if self.material.apply_loss_rate:
            multiplier *= Decimal("1") + self.loss_rate / Decimal("100")
        self.pure_gold_weight = (self.actual_weight * multiplier).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)


class SaleTransaction(models.Model):
    """A sale header. Legacy Order rows are retained for compatibility."""

    STATUS_CHOICES = [("new", "접수"), ("done", "완료"), ("cancel", "취소")]
    transaction_no = models.CharField("거래번호", max_length=11, unique=True, default=generate_transaction_no)
    legacy_transaction_no = models.CharField("기존 거래번호", max_length=30, unique=True, null=True, blank=True)
    import_source = models.CharField("이관 출처", max_length=50, blank=True, db_index=True)
    sale_date = models.DateField("거래일", default=timezone.localdate, db_index=True)
    customer = models.ForeignKey(Customer, verbose_name="거래처", on_delete=models.PROTECT, related_name="sale_transactions")
    status = models.CharField("상태", max_length=10, choices=STATUS_CHOICES, default="new")
    memo = models.TextField("거래 비고", blank=True)
    total_pure_gold_weight = models.DecimalField("총 순금환산중량(g)", max_digits=14, decimal_places=3, default=0)
    total_cash_amount = models.DecimalField("상품/금속 금액", max_digits=14, decimal_places=0, default=0)
    total_labor_amount = models.DecimalField("총 공임", max_digits=14, decimal_places=0, default=0)
    paid_gold_weight = models.DecimalField("금 결제(g)", max_digits=14, decimal_places=3, default=0)
    paid_cash_amount = models.DecimalField("현금 결제", max_digits=14, decimal_places=0, default=0)
    paid_labor_amount = models.DecimalField("공임 결제", max_digits=14, decimal_places=0, default=0)
    gold_receivable = models.DecimalField("순금 미수(g)", max_digits=14, decimal_places=3, default=0)
    cash_receivable = models.DecimalField("현금 미수", max_digits=14, decimal_places=0, default=0)
    labor_receivable = models.DecimalField("공임 미수", max_digits=14, decimal_places=0, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sale_date", "-id"]

    def __str__(self):
        return f"{self.transaction_no} - {self.customer}"

    def refresh_totals(self, save=True):
        items = list(self.items.filter(is_deleted=False).select_related("material"))
        sale_items = [item for item in items if item.entry_type == "sale"]
        return_items = [item for item in items if item.entry_type == "return"]
        payment_items = [item for item in items if item.entry_type == "payment"]
        legacy_adjustment_items = [item for item in items if item.entry_type in ("wg", "dc", "vd")]
        self.total_pure_gold_weight = sum((item.pure_gold_weight for item in sale_items), Decimal("0"))
        self.total_cash_amount = Decimal("0")
        self.total_labor_amount = sum((item.total_amount for item in sale_items), Decimal("0"))
        self.paid_gold_weight = sum((item.pure_gold_weight for item in payment_items), Decimal("0"))
        self.paid_labor_amount = sum((item.total_amount for item in payment_items), Decimal("0"))
        self.paid_cash_amount = Decimal("0")
        returned_gold = sum((item.pure_gold_weight for item in return_items), Decimal("0"))
        returned_labor = sum((item.total_amount for item in return_items), Decimal("0"))
        adjusted_gold = sum((item.pure_gold_weight for item in legacy_adjustment_items), Decimal("0"))
        adjusted_labor = sum(
            (item.total_amount for item in legacy_adjustment_items if item.entry_type in ("dc", "vd")),
            Decimal("0"),
        )
        self.gold_receivable = self.total_pure_gold_weight - returned_gold - self.paid_gold_weight - adjusted_gold
        self.cash_receivable = Decimal("0")
        self.labor_receivable = self.total_labor_amount - returned_labor - self.paid_labor_amount - adjusted_labor
        if save:
            self.save(update_fields=[
                "total_pure_gold_weight", "total_cash_amount", "total_labor_amount",
                "paid_gold_weight", "paid_cash_amount", "paid_labor_amount",
                "gold_receivable", "cash_receivable", "labor_receivable",
            ])


class SaleItem(models.Model):
    ENTRY_TYPE_CHOICES = [
        ("sale", "판매"), ("return", "반품"), ("payment", "결제"),
        ("wg", "WG"), ("dc", "DC"), ("vd", "VD"),
    ]
    transaction = models.ForeignKey(SaleTransaction, verbose_name="판매거래", on_delete=models.CASCADE, related_name="items")
    entry_type = models.CharField("구분", max_length=10, choices=ENTRY_TYPE_CHOICES, default="sale", db_index=True)
    model_number = models.CharField("모델번호", max_length=40)
    product = models.ForeignKey(Product, verbose_name="카탈로그 상품", on_delete=models.PROTECT, null=True, blank=True)
    material = models.ForeignKey(Material, verbose_name="재질", on_delete=models.PROTECT, null=True, blank=True)
    color = models.ForeignKey(ProductColor, verbose_name="색상", on_delete=models.PROTECT, null=True, blank=True)
    weight = models.DecimalField("총중량(g)", max_digits=10, decimal_places=3, default=0)
    settlement_weight = models.DecimalField("정산중량(g)", max_digits=10, decimal_places=3, null=True, blank=True)
    quantity = models.DecimalField("수량", max_digits=12, decimal_places=2, default=1)
    sales_unit = models.CharField("판매 단위", max_length=10, choices=Product.SALES_UNIT_CHOICES, default="piece")
    loss_rate = models.DecimalField("해리율(%)", max_digits=6, decimal_places=2, default=0)
    pure_gold_weight = models.DecimalField("순금환산중량(g)", max_digits=14, decimal_places=3, default=0)
    unit_price = models.DecimalField("단가", max_digits=14, decimal_places=0)
    labor_amount = models.DecimalField("공임", max_digits=14, decimal_places=0, default=0)
    labor_total_override = models.DecimalField("원본 공임합계", max_digits=14, decimal_places=0, null=True, blank=True)
    memo = models.CharField("비고", max_length=200, blank=True)
    purchase_supplier = models.ForeignKey(
        PurchaseSupplier, verbose_name="매입처 스냅샷", on_delete=models.PROTECT,
        null=True, blank=True, related_name="sale_items",
    )
    purchase_loss_rate = models.DecimalField("매입 해리율 스냅샷(%)", max_digits=6, decimal_places=2, null=True, blank=True)
    purchase_labor_amount = models.DecimalField("매입 공임 스냅샷", max_digits=14, decimal_places=0, default=0)
    import_key = models.CharField("이관 행 식별자", max_length=100, unique=True, null=True, blank=True)
    is_deleted = models.BooleanField("삭제", default=False, db_index=True)
    legacy_order = models.OneToOneField(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="migrated_sale_item")
    returned_from = models.ForeignKey(
        "self", verbose_name="원판매 품목", null=True, blank=True,
        on_delete=models.PROTECT, related_name="return_items",
    )

    class Meta:
        ordering = ["id"]

    @property
    def total_weight(self):
        return self.weight

    @property
    def total_amount(self):
        if self.labor_total_override is not None:
            return self.labor_total_override
        return (self.unit_price * self.quantity).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    def calculate_pure_gold_weight(self):
        total = self.settlement_weight if self.settlement_weight is not None else self.total_weight
        if self.product_id and not self.product.weight_required:
            return Decimal("0.000")
        if not self.material or not self.material.apply_loss_rate:
            return total.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        multiplier = self.material.purity_rate * (Decimal("1") + self.loss_rate / Decimal("100"))
        return (total * multiplier).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    def save(self, *args, **kwargs):
        if self.product_id and not self.model_number:
            self.model_number = self.product.code
        if self.product_id:
            self.sales_unit = self.product.sales_unit
            if self.purchase_supplier_id is None:
                self.purchase_supplier = self.product.purchase_supplier
            if self.purchase_loss_rate is None:
                self.purchase_loss_rate = self.product.default_purchase_loss_rate
            if not self.purchase_labor_amount:
                self.purchase_labor_amount = self.product.default_purchase_labor
        self.pure_gold_weight = self.calculate_pure_gold_weight()
        super().save(*args, **kwargs)
