"""The owner's billing console (Django admin): set prices, see every school, record payments."""
from django import forms
from django.contrib import admin, messages
from django.utils import timezone

from . import services
from .models import Invoice, Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "max_students", "monthly_price", "currency", "is_active")
    list_editable = ("monthly_price", "currency", "is_active")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("school", "exempt", "state", "students", "tier", "locked_from", "paid_up_to")
    list_filter = ("exempt",)
    search_fields = ("school__name", "billing_email")
    readonly_fields = ("locked_from", "created_at")
    actions = ["issue_now"]

    @admin.display(description="Status")
    def state(self, obj):
        return services.status(obj.school)["label"]

    @admin.display(description="Students")
    def students(self, obj):
        return services.active_students(obj.school)

    @admin.display(description="Tier")
    def tier(self, obj):
        plan = services.tier_for(services.active_students(obj.school))
        return f"{plan.name} ({plan.currency} {plan.monthly_price})" if plan and plan.monthly_price else (plan.name if plan else "")

    @admin.display(description="Paid up to")
    def paid_up_to(self, obj):
        return services.paid_until(obj.school)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        services.refresh(obj.school)

    @admin.action(description="Issue the next invoice now (if one is due within a week)")
    def issue_now(self, request, queryset):
        made = [i for i in (services.issue_due(s.school) for s in queryset) if i]
        self.message_user(request, f"Issued {len(made)} invoice(s).", messages.SUCCESS)


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = "__all__"

    def clean(self):
        data = super().clean()
        if data.get("status") == Invoice.Status.PAID and not data.get("paid_on"):
            data["paid_on"] = timezone.localdate()
        return data


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    form = InvoiceForm
    list_display = ("number", "school", "amount", "currency", "period_start", "due_on", "status", "paid_on", "school_report")
    list_filter = ("status",)
    search_fields = ("number", "school__name", "payment_reference", "school_report")
    readonly_fields = ("school_reported_at", "school_report", "reminders_sent", "created_at", "recorded_by")
    actions = ["mark_paid_today"]

    def save_model(self, request, obj, form, change):
        was_paid = change and Invoice.objects.filter(pk=obj.pk, status=Invoice.Status.PAID).exists()
        if obj.status == Invoice.Status.PAID and not was_paid:
            services.record_payment(obj, obj.paid_on or timezone.localdate(), obj.payment_method, obj.payment_reference,
                                    by=request.user)
        else:
            super().save_model(request, obj, form, change)
            services.refresh(obj.school)

    @admin.action(description="Mark paid today (method and reference from the school's note)")
    def mark_paid_today(self, request, queryset):
        for invoice in queryset.filter(status=Invoice.Status.OPEN):
            services.record_payment(invoice, timezone.localdate(), invoice.payment_method or Invoice.Method.OTHER,
                                    invoice.payment_reference or invoice.school_report, by=request.user)
        self.message_user(request, "Recorded. The schools have been emailed.", messages.SUCCESS)
