from django.contrib import admin
from .models import School, YearGroup, SchoolClass, Student


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "report_tone", "created_at")


@admin.register(YearGroup)
class YearGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "school")
    list_filter = ("school",)


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("name", "year_group", "house")
    list_filter = ("year_group__school",)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "school", "school_class", "house", "is_active")
    list_filter = ("school", "is_active")
    search_fields = ("first_name", "last_name", "external_id")
