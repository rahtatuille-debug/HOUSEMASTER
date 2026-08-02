from django.contrib import admin
from .models import StudentReport


@admin.register(StudentReport)
class StudentReportAdmin(admin.ModelAdmin):
    list_display = ("student", "term", "status", "tone_used", "generated_at")
    list_filter = ("status", "term", "tone_used")
    search_fields = ("student__first_name", "student__last_name")
