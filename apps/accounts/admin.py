"""金石管理系统 · 账号管理后台."""
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Count
from django.utils import timezone
from django.utils.html import format_html

from .admin_mixins import ADMIN_ONLY, RolePermissionsMixin
from .models import Department, Importance, Notification, NotificationCategory, Role, Team, User


@admin.register(Notification)
class NotificationAdmin(RolePermissionsMixin, admin.ModelAdmin):
    """站内信息箱——未读置顶 + 一键标记已读.

    细则第一页·六:撞单提醒发送到总经办信息箱,信息箱要有明显的未读数量标识。
    修复:此前 has_change_permission 恒为 False,任何人都无法把通知标为已读,
    未读数只增不减。现在所有人可标记自己收件箱的已读状态(表单字段全只读,
    唯一可变的是 read_at)。
    """
    list_display = ("read_badge", "type_badge", "importance_display", "title_display", "content_preview", "recipient", "created_at")
    list_filter = ("recipient", "category", "importance", "read_at")
    search_fields = ("title", "content")
    readonly_fields = ("recipient", "title", "content", "link", "created_at", "read_at")
    date_hierarchy = "created_at"
    actions = ["mark_read", "mark_all_read"]

    VIEW_ROLES = set()  # 任何 staff 都可能收到分配通知,不限于总经办
    CHANGE_ROLES = {Role.SALES, Role.SALES_LEAD, Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.TECH, Role.ADMIN}

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        from django.db.models import Case, IntegerField, Value, When

        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser or getattr(user, "role", None) == Role.ADMIN:
            pass  # 总经办信息箱:可见全部（含发给其他管理员的撞单提醒）
        elif user.is_authenticated:
            qs = qs.filter(recipient=user)  # 普通员工只看自己的
        else:
            return qs.none()
        # 排序:未读置顶 → 高重要置顶 → 新到旧(生产级:重要通知不被淹没)
        return qs.annotate(
            _unread_flag=Case(When(read_at__isnull=True, then=Value(0)), default=Value(1), output_field=IntegerField()),
            _imp_flag=Case(
                When(importance=Importance.HIGH, then=Value(0)),
                When(importance=Importance.MEDIUM, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ),
        ).order_by("_unread_flag", "_imp_flag", "-created_at")

    def get_changelist_instance(self, request):
        cl = super().get_changelist_instance(request)
        unread = self.get_queryset(request).filter(read_at__isnull=True).count()
        if unread:
            cl.title = f"{cl.title}（未读 {unread} 条）"
        return cl

    # 事件类型 → (中文标签, 角标配色)——字段驱动,不再按标题字符串匹配(改文案不断)
    _CAT_STYLE = {
        NotificationCategory.DUPLICATE: ("撞单提醒", "color:#C0392B;background:#FDE8E8"),
        NotificationCategory.ASSIGN_CUSTOMER: ("客户分配", "color:#1D4ED8;background:#DBEAFE"),
        NotificationCategory.DEAL_CONVERT: ("成交立项", "color:#B45309;background:#FEF3C7"),
        NotificationCategory.PROJECT_ASSIGN: ("咨询分配", "color:#1D4ED8;background:#DBEAFE"),
        NotificationCategory.COST_APPLY: ("成本申请", "color:#B45309;background:#FEF3C7"),
        NotificationCategory.PAYMENT_RECORD: ("收款录入", "color:#1D4ED8;background:#DBEAFE"),
        NotificationCategory.SITE_TASK: ("建站任务", "color:#1D4ED8;background:#DBEAFE"),
        NotificationCategory.SITE_TAKEN: ("任务承接", "color:#1D4ED8;background:#DBEAFE"),
        NotificationCategory.SITE_DONE: ("建站完工", "color:#1A7F37;background:#DAFBE1"),
        NotificationCategory.SITE_INFO: ("站点信息", "color:#1D4ED8;background:#DBEAFE"),
        NotificationCategory.POOL_FLOW: ("公海流转", "color:#6B7280;background:#F3F4F6"),
    }
    _DEFAULT_STYLE = ("其他", "color:#6B7280;background:#F3F4F6")

    @admin.display(description="状态")
    def read_badge(self, obj: Notification):
        """未读/已读状态:未读按重要程度配色(高=红强调,其余=琥珀),已读灰——替代 icon-no 红 x."""
        from django.utils.html import format_html
        if obj.is_read:
            return format_html('<span style="color:#6B7280;background:#F3F4F6;border-radius:4px;padding:1px 8px;font-size:12px">已读</span>')
        style = "color:#C0392B;background:#FDE8E8" if obj.importance == Importance.HIGH else "color:#B45309;background:#FEF3C7"
        return format_html('<span style="{};border-radius:4px;padding:1px 8px;font-size:12px;font-weight:600">未读</span>', style)

    @admin.display(description="类型")
    def type_badge(self, obj: Notification) -> str:
        """事件类型角标——按 category 字段驱动(2026-08-29 升级,不再按标题字符串匹配)."""
        cat = obj.category
        if cat in NotificationCategory.values:
            label, style = self._CAT_STYLE.get(NotificationCategory(cat), self._DEFAULT_STYLE)
        else:
            label, style = self._DEFAULT_STYLE
        return format_html('<span style="{};border-radius:4px;padding:1px 8px;font-size:12px">{}</span>', style, label)
    type_badge.admin_order_field = "category"  # type: ignore[attr-defined]

    @admin.display(description="重要程度", ordering="importance")
    def importance_display(self, obj: Notification) -> str:
        """重要程度分级:高=红/中=琥珀/低=灰——高重要一眼可见."""
        if obj.importance == Importance.HIGH:
            return format_html('<span style="color:#C0392B;background:#FDE8E8;border-radius:4px;padding:1px 8px;font-size:12px;font-weight:600">高</span>')
        if obj.importance == Importance.LOW:
            return format_html('<span style="color:#6B7280;background:#F3F4F6;border-radius:4px;padding:1px 8px;font-size:12px">低</span>')
        return format_html('<span style="color:#B45309;background:#FEF3C7;border-radius:4px;padding:1px 8px;font-size:12px">中</span>')

    @admin.display(description="标题")
    def title_display(self, obj: Notification) -> str:
        """未读加粗标色,已读正常灰显——可观测性."""
        if obj.is_read:
            return format_html('<span style="color:#64748B">{}</span>', obj.title)
        return format_html('<b style="color:#1E293B">{}</b>', obj.title)

    @admin.display(description="内容")
    def content_preview(self, obj: Notification) -> str:
        """内容摘要(截断)+ 若有链接给'前往处理'跳转."""
        text = obj.content or ""
        if len(text) > 40:
            text = text[:40] + "…"
        if obj.link:
            return format_html(
                '{} <a href="{}" style="color:#2563EB;text-decoration:none;white-space:nowrap">前往处理 →</a>',
                text, obj.link,
            )
        return text
    content_preview.admin_order_field = "content"  # type: ignore[attr-defined]

    @admin.action(description="标记为已读")
    def mark_read(self, request, queryset):
        updated = queryset.filter(read_at__isnull=True).update(read_at=timezone.now())
        self.message_user(request, f"已标记 {updated} 条通知为已读", messages.SUCCESS)

    @admin.action(description="全部标记为已读")
    def mark_all_read(self, request, queryset):
        updated = self.get_queryset(request).filter(read_at__isnull=True).update(read_at=timezone.now())
        self.message_user(request, f"信息箱已清零（{updated} 条已读）", messages.SUCCESS)


@admin.register(Department)
class DepartmentAdmin(RolePermissionsMixin, admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)

    VIEW_ROLES = ADMIN_ONLY
    CHANGE_ROLES = ADMIN_ONLY
    ADD_ROLES = ADMIN_ONLY
    DELETE_ROLES = ADMIN_ONLY


@admin.register(Team)
class TeamAdmin(RolePermissionsMixin, admin.ModelAdmin):
    """团队管理——v2 claim 新增，支撑销售主管/咨询主管分层权限."""
    list_display = ("name", "department", "lead", "member_count", "created_at")
    list_filter = ("department",)
    search_fields = ("name",)

    VIEW_ROLES = ADMIN_ONLY
    CHANGE_ROLES = ADMIN_ONLY
    ADD_ROLES = ADMIN_ONLY
    DELETE_ROLES = ADMIN_ONLY

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_member_count=Count("members"))

    @admin.display(description="组员数", ordering="_member_count")
    def member_count(self, obj: Team) -> int:
        return obj._member_count


@admin.register(User)
class UserAdmin(RolePermissionsMixin, BaseUserAdmin):
    list_display = ("username", "real_name", "role", "department", "team", "is_team_lead", "is_active", "entry_date")
    list_filter = ("role", "department", "team", "is_active")
    search_fields = ("username", "real_name")

    VIEW_ROLES = ADMIN_ONLY
    CHANGE_ROLES = ADMIN_ONLY
    ADD_ROLES = ADMIN_ONLY
    DELETE_ROLES = ADMIN_ONLY

    fieldsets = BaseUserAdmin.fieldsets + (
        ("金石扩展", {"fields": ("real_name", "role", "department", "team", "is_team_lead", "entry_date", "position")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("金石扩展", {"fields": ("real_name", "role", "department", "team", "is_team_lead", "entry_date", "position")}),
    )
