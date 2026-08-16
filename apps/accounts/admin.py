"""金石管理系统 · 账号管理后台."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Department, Notification, Team, User


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """总经办信息箱——未读数量徽标 + 列表置顶未读."""
    list_display = ("title", "recipient", "is_read", "created_at")
    list_filter = ("recipient", "read_at")
    search_fields = ("title", "content")
    readonly_fields = ("recipient", "title", "content", "link", "created_at", "read_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        role = getattr(request.user, "role", None)
        if role == "admin":
            return qs
        return qs.none()

    def is_read(self, obj: Notification) -> bool:
        return obj.is_read
    is_read.short_description = "已读"  # type: ignore[attr-defined]
    is_read.boolean = True  # type: ignore[attr-defined]


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    """团队管理——v2 claim 新增，支撑销售主管/咨询主管分层权限."""
    list_display = ("name", "department", "lead", "member_count", "created_at")
    list_filter = ("department",)
    search_fields = ("name",)

    def member_count(self, obj: Team) -> int:
        return obj.members.count()
    member_count.short_description = "组员数"  # type: ignore[attr-defined]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "real_name", "role", "department", "team", "is_team_lead", "is_active", "entry_date")
    list_filter = ("role", "department", "team", "is_active")
    search_fields = ("username", "real_name")

    fieldsets = BaseUserAdmin.fieldsets + (
        ("金石扩展", {"fields": ("real_name", "role", "department", "team", "is_team_lead", "entry_date", "position")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("金石扩展", {"fields": ("real_name", "role", "department", "team", "is_team_lead", "entry_date", "position")}),
    )
