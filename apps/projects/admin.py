"""金石管理系统 · 成交项目管理后台——角色分层字段隐藏是本模块核心.

对照细则第二页:
- 权限:销售可见除建站类目/信息外的自己客户;咨询隐藏客户来源;
  技术仅六字段（公司名/成交时间/咨询师/建站类目/信息/进度）
- 收款/支出由咨询师填写,利润自动计算
- 嘉茵（咨询主管）/总经办分配咨询师,二次调配留痕
"""
from decimal import Decimal

from django.contrib import admin, messages
from django.db.models import DecimalField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.template.response import TemplateResponse
from django.utils.html import format_html

from apps.accounts.admin_mixins import PROJECT_EDIT_ROLES, PROJECT_VIEW_ROLES, RolePermissionsMixin
from apps.accounts.models import Role, User
from simple_history.admin import SimpleHistoryAdmin

from .models import Project, ProjectAttachment, ProjectConsultantHistory, ProjectExpense, ProjectPayment, SiteProgress


def _next_seq(history_qs):
    last = history_qs.order_by("-seq").first()
    return (last.seq + 1) if last else 1


class ProjectPaymentInline(admin.TabularInline):
    """收款记录——咨询师可新增多条，兼容分次到账."""
    model = ProjectPayment
    extra = 1
    fields = ("amount", "note", "recorded_by", "recorded_at")
    readonly_fields = ("recorded_by", "recorded_at")

    def has_add_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, "role", None) in (
            Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.ADMIN,
        )

    def has_change_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)


class ProjectExpenseInline(admin.TabularInline):
    """支出记录——咨询师可新增多条."""
    model = ProjectExpense
    extra = 1
    fields = ("amount", "note", "recorded_by", "recorded_at")
    readonly_fields = ("recorded_by", "recorded_at")

    def has_add_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, "role", None) in (
            Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.ADMIN,
        )

    def has_change_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)


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

    def has_add_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, "role", None) in (
            Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.ADMIN,
        )

    def has_delete_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)


# 各角色字段集合定义——对应细则第二页 · 权限功能
ALL_FIELDS = [
    "company_snapshot", "contact_name_snapshot", "phone_snapshot", "deal_business",
    "contract_entity", "is_invoiced", "is_tax_included", "quote_amount",
    "source_snapshot", "note", "sales", "consultant", "created_at", "deal_at",
    "site_category", "site_info", "site_progress",
]

# 销售：隐藏建站类目/信息（细则原文只隐藏这两项,建站进度可见）
SALES_HIDDEN = {"site_category", "site_info"}

# 普通咨询：隐藏客户来源（咨询主管嘉茵不受此限制）
CONSULTANT_HIDDEN = {"source_snapshot"}

# 技术：仅可见六字段
TECH_VISIBLE = {"company_snapshot", "deal_at", "consultant", "site_category", "site_info", "site_progress"}

# 收支/利润三个只读汇总展示字段
MONEY_FIELDS = ["total_income_display", "total_expense_display", "profit_display"]

# 列表页各角色可见列——此前列表列固定,销售/技术在列表页能看到详情页已隐藏的字段
LIST_COLUMNS_DEFAULT = ("company_snapshot", "deal_business", "sales", "consultant", "site_progress", "profit_display")
LIST_COLUMNS_TECH = ("company_snapshot", "deal_at", "consultant", "site_category", "site_progress", "claim_link")


@admin.register(Project)
class ProjectAdmin(RolePermissionsMixin, SimpleHistoryAdmin):
    search_fields = ("company_snapshot", "contact_name_snapshot", "phone_snapshot")
    list_filter = ("site_progress", "is_invoiced")
    readonly_fields = (
        "created_at", "deal_at",
        # 快照字段:客户成交时从客户档案带入,销售已录,只读展示不重复填
        "company_snapshot", "contact_name_snapshot", "phone_snapshot",
        "source_snapshot", "quote_amount", "deal_business", "note",
    ) + tuple(MONEY_FIELDS)

    def formfield_for_dbfield(self, db_field, **kwargs):
        # 下拉按角色过滤:销售人员只列销售、咨询师只列咨询(不再列出全部26个用户)
        from apps.accounts.models import Role
        from django.db.models import Q
        if db_field.name == "sales":
            kwargs["queryset"] = kwargs.get("queryset", User.objects.all()).filter(
                Q(role=Role.SALES) | Q(role=Role.SALES_LEAD) | Q(role=Role.ADMIN)
            )
        elif db_field.name == "consultant":
            kwargs["queryset"] = kwargs.get("queryset", User.objects.all()).filter(
                Q(role=Role.CONSULTANT) | Q(role=Role.CONSULTANT_LEAD) | Q(role=Role.ADMIN)
            )
        elif db_field.name == "tech_assigned":
            # 技术承接人只列技术角色(同类问题:sales/consultant已过滤,tech_assigned漏了)
            kwargs["queryset"] = kwargs.get("queryset", User.objects.all()).filter(
                Q(role=Role.TECH) | Q(role=Role.ADMIN)
            )
        return super().formfield_for_dbfield(db_field, **kwargs)

    # 表单布局规范:短字段并排(2列),长字段(note)独占整行,时间字段组合
    fieldsets = (
        ("项目基本信息", {
            "fields": (
                ("company_snapshot", "contact_name_snapshot"),
                ("phone_snapshot", "deal_business"),
                ("source_snapshot", "quote_amount"),
                "note",
            ),
        }),
        ("成交与归属", {
            "fields": (
                ("sales", "consultant"),
                ("contract_entity", "is_invoiced"),
                ("is_tax_included", "deal_at"),
                "created_at",
            ),
        }),
        ("建站信息", {
            "fields": (
                ("tech_assigned", "site_progress"),
                ("site_category", "site_info"),
                ("site_full_name", "site_domain"),
                ("site_contact_address", "site_contact_phone"),
                ("site_contact_email", "site_icp_number"),
            ),
        }),
        ("财务汇总(自动核算)", {
            "fields": (
                ("total_income_display", "total_expense_display"),
                "profit_display",
            ),
        }),
    )

    actions = ["assign_consultant", "claim_site_task"]

    VIEW_ROLES = PROJECT_VIEW_ROLES
    CHANGE_ROLES = PROJECT_EDIT_ROLES  # 销售 view-only（细则:销售对成交信息只看）
    ADD_ROLES = set()  # 项目由成交动作自动创建,不开放手工新增
    DELETE_ROLES = {Role.ADMIN}

    # ---------- 权限与展示 ----------

    def get_actions(self, request):
        actions = super().get_actions(request)
        role = getattr(request.user, "role", None)
        if role not in (Role.CONSULTANT_LEAD, Role.ADMIN):
            actions.pop("assign_consultant", None)
        return actions

    def get_list_display(self, request):
        if getattr(request.user, "role", None) == Role.TECH:
            return LIST_COLUMNS_TECH
        return LIST_COLUMNS_DEFAULT

    def get_search_fields(self, request):
        if getattr(request.user, "role", None) == Role.TECH:
            return ("company_snapshot",)  # 技术无权按联系人/电话检索
        return self.search_fields

    def get_inlines(self, request, obj):
        role = getattr(request.user, "role", None)
        if role == Role.TECH:
            return []  # 技术只看六个字段，不需要收支/分配历史 inline
        inlines = [ConsultantHistoryInline, ProjectAttachmentInline]
        if role in (Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.ADMIN):
            inlines = [ProjectPaymentInline, ProjectExpenseInline] + inlines
        return inlines

    # ---------- 按角色过滤可见字段 ----------

    def get_fieldsets(self, request, obj=None):
        """fieldsets 按角色动态过滤——Django 有 fieldsets 时 get_fields 被忽略,
        此前技术/销售/咨询字段隐藏未生效(技术详情泄漏联系人/电话/来源等)。"""
        role = getattr(request.user, "role", None)
        fs = [list(g) for g in self.fieldsets]  # 深拷贝,避免污染类级 fieldsets
        if role == Role.TECH:
            keep = TECH_VISIBLE
        elif role == Role.SALES:
            keep = set(ALL_FIELDS) - SALES_HIDDEN
        elif role == Role.CONSULTANT:
            keep = set(ALL_FIELDS) - CONSULTANT_HIDDEN
        else:
            return self.fieldsets
        # 过滤每个分组的字段,保留非空分组
        result = []
        for name, opts in fs:
            fields = opts.get("fields", ())
            flat = []
            for f in fields:
                if isinstance(f, (tuple, list)):
                    flat.append(tuple(x for x in f if x in keep))
                elif f in keep or f in MONEY_FIELDS:
                    flat.append(f)
            flat = [f for f in flat if f not in ((),)]
            if flat:
                result.append((name, {"fields": tuple(flat)}))
        return result

    def get_fields(self, request, obj=None):
        role = getattr(request.user, "role", None)
        if role == Role.TECH:
            return [f for f in ALL_FIELDS if f in TECH_VISIBLE]
        fields = list(ALL_FIELDS)
        if role == Role.SALES:
            fields = [f for f in fields if f not in SALES_HIDDEN]
        elif role == Role.CONSULTANT:
            fields = [f for f in fields if f not in CONSULTANT_HIDDEN]
        else:
            pass  # 咨询主管（嘉茵）/总经办：全字段
        # 收支/利润汇总列——此前只声明在 readonly_fields 里、未进 get_fields,
        # 详情页实际从不展示,收款/支出/利润在表单页不可见
        return fields + MONEY_FIELDS

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        role = getattr(request.user, "role", None)
        if role == Role.SALES:
            # 销售只读，不能改成交项目字段
            return base + [f for f in ALL_FIELDS if f not in SALES_HIDDEN]
        if role == Role.TECH:
            # 技术只能改 site_progress，其余只读
            return base + [f for f in TECH_VISIBLE if f != "site_progress"]
        return base

    @admin.display(description="领取")
    def claim_link(self, obj: Project):
        """技术列表'领取'按钮:未承接显示领取链接,已承接显示承接人."""
        if obj.tech_assigned_id:
            return format_html('<span style="color:#1a7f37">{}</span>', obj.tech_assigned.real_name)
        return format_html(
            '<a href="/admin/projects/project/{}/claim/" style="background:#2563EB;color:#fff!important;padding:4px 12px;border-radius:6px;text-decoration:none;font-size:12px;display:inline-block">领取</a>',
            obj.pk,
        )

    def claim_site_view(self, request, object_id):
        """技术领取建站:记录承接人+通知咨询+留痕,302回列表."""
        from django.shortcuts import redirect
        from django.contrib import messages as msgs
        from apps.accounts.models import Notification
        from apps.customers.models import OperationLog
        role = getattr(request.user, "role", None)
        if role not in (Role.TECH, Role.ADMIN):
            self.message_user(request, "仅技术/总经办可领取建站任务", msgs.ERROR)
            return redirect("/admin/projects/project/")
        project = Project.objects.filter(pk=object_id, tech_assigned__isnull=True).first()
        if not project:
            self.message_user(request, "任务不存在或已被领取", msgs.ERROR)
            return redirect("/admin/projects/project/")
        Project.objects.filter(pk=project.pk).update(tech_assigned=request.user)
        try:
            if project.consultant_id:
                Notification.objects.create(
                    recipient=project.consultant, title="建站任务已承接",
                    content=f"「{project.company_snapshot}」建站任务由 {request.user.real_name} 领取,后续建站事宜请联系该技术。",
                    link=f"/admin/projects/project/{project.pk}/change/",
                )
            OperationLog.objects.create(
                user=request.user, action="承接建站",
                target=f"项目 {project.company_snapshot}",
                detail=f"技术 {request.user.real_name} 领取建站任务",
            )
        except Exception:
            pass
        self.message_user(request, f"已领取建站任务:{project.company_snapshot},已通知咨询", msgs.SUCCESS)
        return redirect("/admin/projects/project/")

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        return [path("<path:object_id>/claim/", self.admin_site.admin_view(self.claim_site_view), name="project_claim_site")] + urls

    @admin.display(description="利润")
    def profit_display(self, obj: Project):
        # 列表页优先用 get_queryset 预聚合的注解值（修复每行 2 次 aggregate 的 N+1）
        income = getattr(obj, "income_annotated", None)
        expense = getattr(obj, "expense_annotated", None)
        if income is not None and expense is not None:
            return income - expense
        return obj.profit

    @admin.display(description="收款汇总")
    def total_income_display(self, obj: Project):
        value = getattr(obj, "income_annotated", None)
        return value if value is not None else obj.total_income

    @admin.display(description="支出汇总")
    def total_expense_display(self, obj: Project):
        value = getattr(obj, "expense_annotated", None)
        return value if value is not None else obj.total_expense

    # ---------- 行级权限 ----------

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        role = getattr(user, "role", None)
        if role == Role.SALES:
            qs = qs.filter(sales=user)
        elif role == Role.SALES_LEAD:
            team = getattr(user, "team", None)
            if team:
                qs = qs.filter(Q(sales__team=team) | Q(sales=user))
            else:
                qs = qs.filter(sales=user)
        elif role == Role.CONSULTANT:
            qs = qs.filter(consultant=user)
        elif role in (Role.FINANCE,):
            return qs.none()  # v2 细则无财务角色
        # TECH / CONSULTANT_LEAD / ADMIN：全部项目（细则只限字段,不限行）
        income_sub = ProjectPayment.objects.filter(project=OuterRef("pk")).values(
            "project"
        ).annotate(s=Sum("amount")).values("s")
        expense_sub = ProjectExpense.objects.filter(project=OuterRef("pk")).values(
            "project"
        ).annotate(s=Sum("amount")).values("s")
        return qs.annotate(
            income_annotated=Coalesce(
                Subquery(income_sub), Decimal("0"), output_field=DecimalField(),
            ),
            expense_annotated=Coalesce(
                Subquery(expense_sub), Decimal("0"), output_field=DecimalField(),
            ),
        )

    def save_model(self, request, obj, form, change):
        """技术仅可更新 site_progress（表单层已只读其余字段,这里只落这一个字段）."""
        role = getattr(request.user, "role", None)
        if role == Role.TECH and change:
            Project.objects.filter(pk=obj.pk).update(site_progress=obj.site_progress)
            # 建站任务流转:技术更新进度时若无人承接 → 记录承接人 + 通知对应咨询 + 留痕
            if not obj.tech_assigned_id and obj.site_progress != SiteProgress.NOT_STARTED:
                Project.objects.filter(pk=obj.pk).update(tech_assigned=request.user)
                try:
                    from apps.accounts.models import Notification
                    if obj.consultant_id:
                        Notification.objects.create(
                            recipient=obj.consultant, title="建站任务已承接",
                            content=f"「{obj.company_snapshot}」建站任务由 {request.user.real_name} 接手（进度:{obj.get_site_progress_display()}），后续建站事宜请联系该技术。",
                            link=f"/admin/projects/project/{obj.pk}/change/",
                        )
                    from apps.customers.models import OperationLog
                    OperationLog.objects.create(
                        user=request.user, action="承接建站",
                        target=f"项目 {obj.company_snapshot}",
                        detail=f"技术 {request.user.real_name} 承接建站,进度:{obj.get_site_progress_display()}",
                    )
                except Exception:
                    pass
            return
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        # 此前未处理 deleted_objects:在 inline 里勾删收款/支出行实际不生效
        for obj in formset.deleted_objects:
            obj.delete()
        for instance in instances:
            if isinstance(instance, (ProjectPayment, ProjectExpense)) and not instance.recorded_by_id:
                instance.recorded_by = request.user
            if isinstance(instance, ProjectAttachment) and not instance.uploaded_by_id:
                instance.uploaded_by = request.user
            instance.save()
        formset.save_m2m()

    # ---------- 分配咨询师 Action（嘉茵/总经办专用） ----------

    @admin.action(description="分配/调配咨询师")
    @admin.action(description="领取建站任务（技术承接）")
    def claim_site_task(self, request, queryset):
        """技术领取建站任务:记录承接人 + 通知对应咨询 + 留痕."""
        role = getattr(request.user, "role", None)
        if role not in (Role.TECH, Role.ADMIN):
            self.message_user(request, "仅技术/总经办可领取建站任务", messages.ERROR)
            return
        from apps.accounts.models import Notification
        from apps.customers.models import OperationLog
        cnt = 0
        for project in queryset.filter(tech_assigned__isnull=True):
            Project.objects.filter(pk=project.pk).update(tech_assigned=request.user)
            try:
                if project.consultant_id:
                    Notification.objects.create(
                        recipient=project.consultant, title="建站任务已承接",
                        content=f"「{project.company_snapshot}」建站任务由 {request.user.real_name} 领取,后续建站事宜请联系该技术。",
                        link=f"/admin/projects/project/{project.pk}/change/",
                    )
                OperationLog.objects.create(
                    user=request.user, action="承接建站",
                    target=f"项目 {project.company_snapshot}",
                    detail=f"技术 {request.user.real_name} 领取建站任务",
                )
            except Exception:
                pass
            cnt += 1
        self.message_user(request, f"已领取 {cnt} 个建站任务,承接人=自己,已通知对应咨询", messages.SUCCESS)

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
            new_consultant = User.objects.filter(
                id=new_consultant_id, is_active=True, role=Role.CONSULTANT,
            ).first()
            if new_consultant is None:
                self.message_user(request, "目标人员无效（需为在职咨询师）", messages.ERROR)
                return None
            cnt = 0
            for project in queryset:
                ProjectConsultantHistory.objects.create(
                    project=project, from_consultant=project.consultant, to_consultant=new_consultant,
                    assigned_by=request.user, seq=_next_seq(project.consultant_history),
                )
                project.consultant = new_consultant
                project.save(update_fields=["consultant"])
                cnt += 1
            self.message_user(request, f"已将 {cnt} 个项目分配给 {new_consultant.real_name}", messages.SUCCESS)
            return None
        consultants = User.objects.filter(role=Role.CONSULTANT, is_active=True)
        context = dict(
            self.admin_site.each_context(request),
            title="分配/调配咨询师",
            action_checkbox_name=admin.helpers.ACTION_CHECKBOX_NAME,
            queryset=queryset,
            consultants=consultants,
        )
        return TemplateResponse(request, "admin/projects/assign_consultant.html", context)
