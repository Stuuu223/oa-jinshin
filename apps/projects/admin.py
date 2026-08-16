"""金石管理系统 · 成交项目管理后台——角色分层字段隐藏是本模块核心."""
from django.contrib import admin
from django.contrib import messages
from django.template.response import TemplateResponse
from django.utils import timezone

from apps.accounts.models import LEAD_ROLES, Role

from .models import Project, ProjectAttachment, ProjectConsultantHistory, ProjectExpense, ProjectPayment


class ProjectPaymentInline(admin.TabularInline):
    """收款记录——咨询师可新增多条，兼容分次到账."""
    model = ProjectPayment
    extra = 1
    fields = ("amount", "note", "recorded_by", "recorded_at")
    readonly_fields = ("recorded_by", "recorded_at")


class ProjectExpenseInline(admin.TabularInline):
    """支出记录——咨询师可新增多条."""
    model = ProjectExpense
    extra = 1
    fields = ("amount", "note", "recorded_by", "recorded_at")
    readonly_fields = ("recorded_by", "recorded_at")


class ConsultantHistoryInline(admin.TabularInline):
    """咨询师分配历史——只读时间线，显示第一次/二次分配记录."""
    model = ProjectConsultantHistory
    extra = 0
    fields = ("seq", "from_consultant", "to_consultant", "assigned_by", "assigned_at")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class ProjectAttachmentInline(admin.TabularInline):
    model = ProjectAttachment
    extra = 0
    fields = ("file", "uploaded_by", "uploaded_at")
    readonly_fields = ("uploaded_by", "uploaded_at")


# 各角色字段集合定义——对应 claim 第二页 · 二、权限功能
ALL_FIELDS = [
    "company_snapshot", "contact_name_snapshot", "phone_snapshot", "deal_business",
    "contract_entity", "is_invoiced", "is_tax_included", "quote_amount",
    "source_snapshot", "note", "sales", "consultant", "created_at", "deal_at",
    "site_category", "site_info", "site_progress",
]

# 销售：隐藏建站类目/信息
SALES_HIDDEN = {"site_category", "site_info"}

# 普通咨询：隐藏客户来源（咨询主管嘉茵不受此限制）
CONSULTANT_HIDDEN = {"source_snapshot"}

# 技术：仅可见六字段
TECH_VISIBLE = {"company_snapshot", "deal_at", "consultant", "site_category", "site_info", "site_progress"}


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("company_snapshot", "deal_business", "sales", "consultant", "site_progress", "profit_display")
    search_fields = ("company_snapshot", "contact_name_snapshot", "phone_snapshot")
    list_filter = ("site_progress", "is_invoiced")
    readonly_fields = ("created_at", "deal_at", "profit_display", "total_income_display", "total_expense_display")

    actions = ["assign_consultant"]

    def get_inlines(self, request, obj):
        role = getattr(request.user, "role", None)
        if role == Role.TECH:
            return []  # 技术只看六个字段，不需要收支/分配历史 inline
        inlines = [ConsultantHistoryInline, ProjectAttachmentInline]
        if role in (Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.ADMIN):
            inlines = [ProjectPaymentInline, ProjectExpenseInline] + inlines
        return inlines

    # ---------- 按角色过滤可见字段 ----------
    def get_fields(self, request, obj=None):
        role = getattr(request.user, "role", None)
        if role == Role.TECH:
            return [f for f in ALL_FIELDS if f in TECH_VISIBLE]
        if role == Role.SALES:
            return [f for f in ALL_FIELDS if f not in SALES_HIDDEN]
        if role == Role.CONSULTANT:
            return [f for f in ALL_FIELDS if f not in CONSULTANT_HIDDEN]
        # 咨询主管（嘉茵）/总经办：全字段可见
        return ALL_FIELDS

    def get_readonly_fields(self, request, obj=None):
        base = list(self.readonly_fields)
        role = getattr(request.user, "role", None)
        if role == Role.SALES:
            # 销售只读，不能改成交项目字段
            return base + [f for f in ALL_FIELDS if f not in SALES_HIDDEN]
        if role == Role.TECH:
            # 技术只能改 site_progress，其余只读
            return base + [f for f in TECH_VISIBLE if f != "site_progress"]
        return base

    def profit_display(self, obj: Project):
        return obj.profit
    profit_display.short_description = "利润"  # type: ignore[attr-defined]

    def total_income_display(self, obj: Project):
        return obj.total_income
    total_income_display.short_description = "收款汇总"  # type: ignore[attr-defined]

    def total_expense_display(self, obj: Project):
        return obj.total_expense
    total_expense_display.short_description = "支出汇总"  # type: ignore[attr-defined]

    # ---------- 行级权限 ----------
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        role = getattr(user, "role", None)
        if role == Role.SALES:
            return qs.filter(sales=user)
        if role == Role.SALES_LEAD:
            team = getattr(user, "team", None)
            if team:
                return qs.filter(sales__team=team)
            return qs.filter(sales=user)
        if role == Role.CONSULTANT:
            return qs.filter(consultant=user)
        if role == Role.TECH:
            return qs  # 技术看全部项目，仅字段级限制，不按 assignee 行级过滤
        return qs  # 咨询主管/总经办看全部

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, (ProjectPayment, ProjectExpense)) and not instance.recorded_by_id:
                instance.recorded_by = request.user
            if isinstance(instance, ProjectAttachment) and not instance.uploaded_by_id:
                instance.uploaded_by = request.user
            instance.save()
        formset.save_m2m()

    # ---------- 分配咨询师 Action（嘉茵/总经办专用） ----------
    @admin.action(description="🎯 分配/调配咨询师")
    def assign_consultant(self, request, queryset):
        role = getattr(request.user, "role", None)
        if role not in (Role.CONSULTANT_LEAD, Role.ADMIN):
            self.message_user(request, "仅咨询主管（嘉茵）/总经办可分配咨询师", messages.ERROR)
            return
        if "apply" in request.POST:
            new_consultant_id = request.POST.get("new_consultant")
            if not new_consultant_id:
                self.message_user(request, "请选择目标咨询师", messages.ERROR)
                return None
            from apps.accounts.models import User
            new_consultant = User.objects.get(id=new_consultant_id)
            cnt = 0
            for project in queryset:
                last = project.consultant_history.order_by("-seq").first()
                next_seq = (last.seq + 1) if last else 1
                ProjectConsultantHistory.objects.create(
                    project=project, from_consultant=project.consultant, to_consultant=new_consultant,
                    assigned_by=request.user, seq=next_seq,
                )
                project.consultant = new_consultant
                project.save(update_fields=["consultant"])
                cnt += 1
            self.message_user(request, f"已将 {cnt} 个项目分配给 {new_consultant.real_name}", messages.SUCCESS)
            return None
        from apps.accounts.models import Role as RoleEnum, User
        consultants = User.objects.filter(role=RoleEnum.CONSULTANT, is_active=True)
        context = dict(
            self.admin_site.each_context(request),
            title="分配/调配咨询师",
            action_checkbox_name=admin.helpers.ACTION_CHECKBOX_NAME,
            queryset=queryset,
            consultants=consultants,
        )
        return TemplateResponse(request, "admin/projects/assign_consultant.html", context)
