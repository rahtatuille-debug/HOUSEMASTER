from django.contrib import admin

from .models import C2BPayment, MpesaAccount, StkRequest


@admin.register(C2BPayment)
class C2BPaymentAdmin(admin.ModelAdmin):
    """Payments made straight to a paybill: the owner's (subscriptions) and the schools' (fees)."""
    list_display = ("paid_at", "purpose", "school", "amount", "bill_ref", "trans_id", "status")
    list_filter = ("purpose", "status")
    search_fields = ("trans_id", "bill_ref", "payer_name")
    readonly_fields = [f.name for f in C2BPayment._meta.fields]


@admin.register(StkRequest)
class StkRequestAdmin(admin.ModelAdmin):
    list_display = ("created_at", "purpose", "school", "amount", "status", "receipt")
    list_filter = ("purpose", "status")
    readonly_fields = [f.name for f in StkRequest._meta.fields]


@admin.register(MpesaAccount)
class MpesaAccountAdmin(admin.ModelAdmin):
    """The schools' own M-Pesa connections. The keys are encrypted and never shown."""
    list_display = ("school", "kind", "shortcode", "environment", "enabled", "c2b_registered_at")
    exclude = ("consumer_key", "consumer_secret", "passkey", "callback_token")
    readonly_fields = ("school", "kind", "shortcode", "till_number", "environment", "c2b_registered_at")
