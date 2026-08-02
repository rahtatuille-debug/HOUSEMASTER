from django.contrib import admin
from .models import Subject, Term, Grade


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "school")
    list_filter = ("school",)


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "start_date", "end_date")
    list_filter = ("school",)


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("student", "subject", "term", "score", "max_score")
    list_filter = ("subject", "term")
    search_fields = ("student__first_name", "student__last_name")
