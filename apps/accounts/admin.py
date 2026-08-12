"""金石管理系统 · 账号管理后台."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Department, User


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "real_name", "role", "department", "is_active", "entry_date")
    list_filter = ("role", "department", "is_active")
    search_fields = ("username", "real_name")

    fieldsets = BaseUserAdmin.fieldsets + (
        ("金石扩展", {"fields": ("real_name", "role", "department", "entry_date", "position")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("金石扩展", {"fields": ("real_name", "role", "department", "entry_date", "position")}),
    )
