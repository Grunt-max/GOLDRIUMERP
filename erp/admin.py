from django.contrib import admin
from .models import CompanyProfile, Customer, DailyActivity, DailyActivityPhoto, DailySaleSequence, Factory, GoldLedgerEntry, GoldPrice, MarketplaceProduct, Material, OpenMarketChannelOffer, OpenMarketChannelSetting, OpenMarketMatchCandidate, OpenMarketProduct, OpenMarketProductImage, OpenMarketVariant, Order, Product, ProductColor, PurchaseBatch, PurchaseEntry, PurchaseSupplier, SaleItem, SaleTransaction


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("name", "purity_rate", "default_loss_rate", "apply_loss_rate", "active")


@admin.register(ProductColor)
class ProductColorAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "active")


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ("supplier_name", "supplier_phone")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "customer_type", "contact", "phone", "default_loss_rate", "created_at")
    search_fields = ("name", "contact", "phone")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "default_loss_rate", "unit_price", "stock_quantity", "active", "is_deleted")
    list_filter = ("active", "is_deleted", "material", "color")
    search_fields = ("name", "code")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "model_number", "source_type", "delivery_type", "quantity", "fulfilled_quantity", "status", "ordered_at", "due_date")
    list_filter = ("source_type", "delivery_type", "status", "ordered_at", "due_date")
    search_fields = ("customer__name", "model_number", "raw_order_text", "option_detail")


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    fields = ("entry_type", "model_number", "material", "color", "weight", "quantity", "unit_price", "is_deleted")


@admin.register(SaleTransaction)
class SaleTransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction_no", "sale_date", "customer", "cash_receivable", "labor_receivable", "gold_receivable")
    list_filter = ("status", "sale_date")
    search_fields = ("transaction_no", "customer__name")
    inlines = [SaleItemInline]


@admin.register(DailySaleSequence)
class DailySaleSequenceAdmin(admin.ModelAdmin):
    list_display = ("sale_date", "last_sequence")
    readonly_fields = ("sale_date", "last_sequence")


@admin.register(DailyActivity)
class DailyActivityAdmin(admin.ModelAdmin):
    list_display = ("activity_date", "content", "image", "created_by", "is_deleted", "created_at")
    list_filter = ("activity_date", "created_by")
    search_fields = ("content",)


@admin.register(DailyActivityPhoto)
class DailyActivityPhotoAdmin(admin.ModelAdmin):
    list_display = ("activity", "image", "uploaded_at")


@admin.register(Factory)
class FactoryAdmin(admin.ModelAdmin):
    list_display = ("name", "contact", "phone", "active")


@admin.register(GoldLedgerEntry)
class GoldLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("entry_date", "factory", "entry_type", "material", "actual_weight", "pure_gold_weight", "cash_amount", "is_deleted")
    list_filter = ("entry_type", "entry_date", "factory", "is_deleted")


@admin.register(GoldPrice)
class GoldPriceAdmin(admin.ModelAdmin):
    list_display = ("market_type", "price_date", "source_price_per_gram", "application_rate", "applied_price_per_gram", "applied_price_per_don", "is_confirmed", "collected_at")
    list_filter = ("market_type", "is_confirmed", "source_name")


@admin.register(MarketplaceProduct)
class MarketplaceProductAdmin(admin.ModelAdmin):
    list_display = ("channel", "external_product_id", "name", "master_product", "status", "sale_price", "option_count", "synced_at")
    list_filter = ("channel", "status")
    search_fields = ("external_product_id", "name")
    readonly_fields = ("channel", "external_product_id", "name", "status", "category_code", "product_url", "image_url", "sale_price", "option_count", "raw_data", "synced_at")


class OpenMarketVariantInline(admin.TabularInline):
    model = OpenMarketVariant
    extra = 0


class OpenMarketProductImageInline(admin.TabularInline):
    model = OpenMarketProductImage
    extra = 0


class OpenMarketChannelSettingInline(admin.StackedInline):
    model = OpenMarketChannelSetting
    extra = 0


@admin.register(OpenMarketProduct)
class OpenMarketProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "brand", "category", "active", "updated_at")
    list_filter = ("active", "category")
    search_fields = ("code", "name", "brand")
    inlines = (OpenMarketVariantInline, OpenMarketChannelSettingInline, OpenMarketProductImageInline)


@admin.register(OpenMarketChannelOffer)
class OpenMarketChannelOfferAdmin(admin.ModelAdmin):
    list_display = ("listing", "external_option_id", "option_name", "display_price", "sale_status", "synced_at")
    list_filter = ("listing__channel", "sale_status")
    search_fields = ("listing__name", "external_option_id", "option_name")


@admin.register(OpenMarketMatchCandidate)
class OpenMarketMatchCandidateAdmin(admin.ModelAdmin):
    list_display = ("naver_listing", "coupang_listing", "name_score", "status")
    list_filter = ("status",)


@admin.register(PurchaseSupplier)
class PurchaseSupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact", "phone", "default_loss_rate", "active")


@admin.register(PurchaseEntry)
class PurchaseEntryAdmin(admin.ModelAdmin):
    list_display = ("purchase_date", "supplier", "item_name", "material", "actual_weight", "loss_rate", "pure_gold_weight", "purchase_amount", "is_deleted")
    list_filter = ("purchase_date", "material", "is_deleted")


@admin.register(PurchaseBatch)
class PurchaseBatchAdmin(admin.ModelAdmin):
    list_display = ("reference_no", "purchase_date", "supplier", "image", "created_at")
