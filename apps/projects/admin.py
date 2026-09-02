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
from apps.accounts.models import Importance, NotificationCategory, Role, User
from apps.accounts.services import notify
from simple_history.admin import SimpleHistoryAdmin

from .models import Project, ProjectAttachment, ProjectConsultantHistory, ProjectExpense, ProjectPayment, SiteCategory, SiteProgress


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
    # 站点联系方式(咨询填写,衔接办证/建站)
    "site_full_name", "site_contact_address", "site_contact_phone", "site_contact_email",
    "site_domain_icp", "tech_assigned",
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

    def get_list_filter(self, request):
        """技术列表筛选净化:只留建站进度(是否开票与己无关),其他角色保持两个筛选."""
        if getattr(request.user, "role", None) == Role.TECH:
            return ["site_progress"]
        return ("site_progress", "is_invoiced")
    readonly_fields = (
        "created_at", "deal_at",
        # 快照字段:客户成交时从客户档案带入,销售已录,只读展示不重复填
        "company_snapshot", "contact_name_snapshot", "phone_snapshot",
        "source_snapshot", "quote_amount", "deal_business", "note",
        # 签约主体:成交时即确定为合同签约主体(一般=公司名),只读不重复填
        "contract_entity",
        # 建站类目:由成交业务自动带出(如成交业务'ICPEDI 双证办理'→类目ICPEDI),全员只读不再手动选
        "site_category",
    ) + tuple(MONEY_FIELDS)

    def formfield_for_dbfield(self, db_field, **kwargs):
        # 下拉按角色过滤:销售人员只列销售/销售主管、咨询师只列咨询/咨询主管(不含总经办/测试账号)
        from apps.accounts.models import Role
        from django.db.models import Q
        base_qs = kwargs.get("queryset", User.objects.all()).exclude(username__startswith="test_")
        if db_field.name == "sales":
            kwargs["queryset"] = base_qs.filter(
                Q(role=Role.SALES) | Q(role=Role.SALES_LEAD)
            )
        elif db_field.name == "consultant":
            kwargs["queryset"] = base_qs.filter(
                Q(role=Role.CONSULTANT) | Q(role=Role.CONSULTANT_LEAD)
            )
        elif db_field.name == "tech_assigned":
            kwargs["queryset"] = base_qs.filter(role=Role.TECH)
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
                ("site_full_name", "site_domain_icp"),
                ("site_contact_address", "site_contact_phone"),
                ("site_contact_email",),
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
        if role not in (Role.TECH, Role.ADMIN):
            actions.pop("claim_site_task", None)  # 领取建站仅技术/总经办
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
                elif f in keep or (f in MONEY_FIELDS and role != Role.TECH):
                    # 财务汇总三字段按角色保留(销售/咨询/咨询主管/总经办可看),技术部除外(细则:技术看不到财务)
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
        if role == Role.CONSULTANT:
            # 普通咨询:可填建站类目/信息/站点联系方式;归属/签约/进度非其职责只读
            return base + ["sales", "consultant", "is_invoiced", "is_tax_included", "site_progress"]
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
        from apps.customers.models import OperationLog
        role = getattr(request.user, "role", None)
        if role not in (Role.TECH, Role.ADMIN):
            self.message_user(request, "仅技术/总经办可领取建站任务", msgs.ERROR)
            return redirect("/admin/tech-workbench/")
        project = Project.objects.filter(pk=object_id, tech_assigned__isnull=True).first()
        if not project:
            self.message_user(request, "任务不存在或已被领取", msgs.ERROR)
            return redirect("/admin/tech-workbench/")
        # 承接=开始搭建:自动更新进度为进行中(用户:承接后不该还是待开始)
        Project.objects.filter(pk=project.pk).update(tech_assigned=request.user, site_progress=SiteProgress.IN_PROGRESS)
        try:
            if project.consultant_id:
                notify(
                    category=NotificationCategory.SITE_TAKEN,
                    importance=Importance.MEDIUM,
                    recipients=project.consultant,
                    title="建站任务已承接",
                    content=f"「{project.company_snapshot}」建站任务由 {request.user.real_name} 领取,后续建站事宜请联系该技术。",
                    link=f"/admin/projects/project/{project.pk}/change/",
                    actor=request.user,
                    entity_type="project",
                    entity_id=project.pk,
                )
            OperationLog.objects.create(
                user=request.user, action="承接建站",
                target=f"项目 {project.company_snapshot}",
                detail=f"技术 {request.user.real_name} 领取建站任务",
            )
        except Exception:
            pass
        self.message_user(request, f"已领取建站任务:{project.company_snapshot},已通知咨询", msgs.SUCCESS)
        return redirect("/admin/tech-workbench/")

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
        # 建站类目=成交业务派生字段(只读):每次保存都按业务推断(非仅空时)——旧自由文本值/人工值一律纠正为业务对应类目
        if obj.deal_business:
            db = obj.deal_business
            if "ICPEDI" in db:
                obj.site_category = SiteCategory.ICPEDI
            elif "EDI" in db:
                obj.site_category = SiteCategory.EDI
            elif "ICP" in db:
                obj.site_category = SiteCategory.ICP
            elif "官网" in db or "企业" in db:
                obj.site_category = SiteCategory.CORP_SITE_ICP
            elif "APP" in db.upper() or "小程序" in db:
                obj.site_category = SiteCategory.APP
        if role == Role.TECH and change:
            Project.objects.filter(pk=obj.pk).update(site_progress=obj.site_progress)
            # 建站任务流转:技术更新进度时若无人承接 → 记录承接人 + 同步进度为进行中(承接=开工,防'已承接待开始'不一致)
            if not obj.tech_assigned_id and obj.site_progress != SiteProgress.NOT_STARTED:
                Project.objects.filter(pk=obj.pk).update(tech_assigned=request.user, site_progress=SiteProgress.IN_PROGRESS)
                try:
                    if obj.consultant_id:
                        notify(
                            category=NotificationCategory.SITE_TAKEN,
                            importance=Importance.MEDIUM,
                            recipients=obj.consultant,
                            title="建站任务已承接",
                            content=f"「{obj.company_snapshot}」建站任务由 {request.user.real_name} 接手（进度:{obj.get_site_progress_display()}），后续建站事宜请联系该技术。",
                            link=f"/admin/projects/project/{obj.pk}/change/",
                            actor=request.user,
                            entity_type="project",
                            entity_id=obj.pk,
                        )
                    from apps.customers.models import OperationLog
                    OperationLog.objects.create(
                        user=request.user, action="承接建站",
                        target=f"项目 {obj.company_snapshot}",
                        detail=f"技术 {request.user.real_name} 承接建站,进度:{obj.get_site_progress_display()}",
                    )
                except Exception:
                    pass
            # 建站完工 → 同步咨询/销售/管理层(闭环亮点:完工状态同步全员)
            if obj.site_progress in (SiteProgress.COMPLETED_PENDING, SiteProgress.DEPLOYED):
                try:
                    done_users = []
                    if obj.consultant_id:
                        done_users.append(obj.consultant)
                    if obj.sales_id and obj.sales not in done_users:
                        done_users.append(obj.sales)
                    admins = list(
                        User.objects.filter(role=Role.ADMIN, is_active=True).exclude(pk__in=[u.pk for u in done_users])
                    )
                    notify(
                        category=NotificationCategory.SITE_DONE,
                        importance=Importance.HIGH,
                        recipients=done_users + admins,
                        title="建站任务已完工",
                        content=f"「{obj.company_snapshot}」建站任务已完工,进度同步全员。",
                        link=f"/admin/projects/project/{obj.pk}/change/",
                        actor=request.user,
                        entity_type="project",
                        entity_id=obj.pk,
                    )
                except Exception:
                    pass
            return
        super().save_model(request, obj, form, change)
        # 建站任务进池:确认建站类目(由成交业务自动带出)且尚无技术承接 → 通知技术部领取
        if obj.tech_assigned_id is None and obj.site_category and change and (
            set(form.changed_data) & {"deal_business", "site_category"}
        ):
            try:
                techs = list(User.objects.filter(role=Role.TECH, is_active=True))
                notify(
                    category=NotificationCategory.SITE_TASK,
                    importance=Importance.HIGH,
                    recipients=techs,
                    title="新建站任务待领取",
                    content=f"「{obj.company_snapshot}」建站任务已进入任务池（类目:{obj.get_site_category_display()}），请到技术数据总览领取。",
                    link="/admin/tech-workbench/",
                    actor=request.user,
                    entity_type="project",
                    entity_id=obj.pk,
                )
            except Exception:
                pass
        # 站点交接信息流转:咨询/管理层更新站点字段(域名与备案/联系方式/信息)且已有技术承接 → 通知技术
        SITE_FIELDS = {"site_info", "site_full_name", "site_contact_address", "site_contact_phone",
                       "site_contact_email", "site_domain_icp"}
        if obj.tech_assigned_id and change and (set(form.changed_data) & SITE_FIELDS):
            try:
                notify(
                    category=NotificationCategory.SITE_INFO,
                    importance=Importance.MEDIUM,
                    recipients=obj.tech_assigned,
                    title="站点交接信息已更新",
                    content=f"「{obj.company_snapshot}」站点信息(域名/备案/联系方式/备注)已更新,请到技术数据总览查看。",
                    link="/admin/tech-workbench/",
                    actor=request.user,
                    entity_type="project",
                    entity_id=obj.pk,
                )
            except Exception:
                pass

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
            # 收款录入/成本申请 → 通知财务/总经办(财务部角色搁置,由总经办承担;留痕不复核,记录即知会)
            try:
                admins = list(User.objects.filter(role=Role.ADMIN, is_active=True))
                if isinstance(instance, ProjectPayment) and admins:
                    notify(
                        category=NotificationCategory.PAYMENT_RECORD,
                        importance=Importance.HIGH,
                        recipients=admins,
                        title="收款记录已录入",
                        content=f"「{instance.project.company_snapshot}」录入收款 ¥{instance.amount}（{request.user.real_name}），请知悉。",
                        link=f"/admin/projects/project/{instance.project_id}/change/",
                        actor=request.user,
                        entity_type="project",
                        entity_id=instance.project_id,
                        dedup=False,
                    )
                elif isinstance(instance, ProjectExpense) and admins:
                    notify(
                        category=NotificationCategory.COST_APPLY,
                        importance=Importance.HIGH,
                        recipients=admins,
                        title="成本支出已申请",
                        content=f"「{instance.project.company_snapshot}」申请支出 ¥{instance.amount}（{instance.note or '无备注'}），请知悉。",
                        link=f"/admin/projects/project/{instance.project_id}/change/",
                        actor=request.user,
                        entity_type="project",
                        entity_id=instance.project_id,
                        dedup=False,
                    )
            except Exception:
                pass
        formset.save_m2m()

    # ---------- 建站领取 Action（技术/总经办专用） ----------

    @admin.action(description="领取建站任务（技术承接）")
    def claim_site_task(self, request, queryset):
        """技术领取建站任务:记录承接人 + 通知对应咨询 + 留痕."""
        role = getattr(request.user, "role", None)
        if role not in (Role.TECH, Role.ADMIN):
            self.message_user(request, "仅技术/总经办可领取建站任务", messages.ERROR)
            return
        from apps.customers.models import OperationLog
        cnt = 0
        for project in queryset.filter(tech_assigned__isnull=True):
            Project.objects.filter(pk=project.pk).update(tech_assigned=request.user)
            try:
                if project.consultant_id:
                    notify(
                        category=NotificationCategory.SITE_TAKEN,
                        importance=Importance.MEDIUM,
                        recipients=project.consultant,
                        title="建站任务已承接",
                        content=f"「{project.company_snapshot}」建站任务由 {request.user.real_name} 领取,后续建站事宜请联系该技术。",
                        link=f"/admin/projects/project/{project.pk}/change/",
                        actor=request.user,
                        entity_type="project",
                        entity_id=project.pk,
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

    # ---------- 分配咨询师 Action（嘉茵/总经办专用） ----------

    @admin.action(description="分配/调配咨询师")
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
            # 主管分配后 → 通知具体咨询师(用户要求:成交立项先通知主管,分配后通知咨询师本人)
            try:
                notify(
                    category=NotificationCategory.PROJECT_ASSIGN,
                    importance=Importance.MEDIUM,
                    recipients=new_consultant,
                    title="项目分配通知",
                    content=f"{request.user.real_name} 将 {cnt} 个项目分配给你,请及时办证跟进。",
                    link="/admin/projects/project/",
                    actor=request.user,
                )
            except Exception:
                pass
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
