"""金石管理系统 · 客户管理后台——M1 核心 + v2 客户池广场/撤销栈 + 回收站 + 撞单预检.

对照《金石企服客户管理系统搭建细则》第一页:
- 三、权限:销售看自己/主管看组员+自己/总经办看全部
- 四、分配:主管/总经办可分配管辖内客户（不限公海）并撤回
- 五、客户池广场:释放后全员可见,获取后归属到获取人,来源栏署名"客户池广场-XX"
- 六、撞单:录入前 JS 预检弹窗 + 录入后标识 + 送总经办信息箱
- 七、回收站:删除进回收站（软删）,总经办可查看已删客户及全部修改记录
"""
import threading

from django import forms
from django.contrib import admin, messages
from django.db.models import Q
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html

from apps.accounts.admin_mixins import FIRST_PAGE_ROLES, RolePermissionsMixin
from apps.accounts.models import Importance, NotificationCategory, Role, User
from apps.accounts.services import notify
from simple_history.admin import SimpleHistoryAdmin

from .models import (
    Cost,
    CostStatus,
    Customer,
    Receipt,
    CustomerAttachment,
    CustomerOwnerHistory,
    CustomerStatus,
    DealStatus,
    FollowUp,
    OperationLog,
    VisitLog,
    OwnerHistorySourceType,
    PoolType,
    RecycledCustomer,
    Source,
)

# phone_masked 列需要感知请求者角色；ModelAdmin 实例多线程共享，
# 存在 self 上会串号，改存 thread-local
_request_local = threading.local()


def _next_seq(history_qs):
    """栈式归属历史的下一次 seq——统一收敛,原先 4 处复制粘贴."""
    last = history_qs.order_by("-seq").first()
    return (last.seq + 1) if last else 1


class StatusFilter(admin.SimpleListFilter):
    title = "状态"
    parameter_name = "status"
    def lookups(self, request, model_admin):
        return [(None, "全部")] + CustomerStatus.choices
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(status=self.value())
        return queryset


class SourceFilter(admin.SimpleListFilter):
    title = "来源"
    parameter_name = "source"
    def lookups(self, request, model_admin):
        # 来源已改为自由文本:存量枚举值已迁移为中文标签(referral→转介绍 等);
        # square 保留枚举值(客户池广场署名逻辑依赖),其余按中文标签作筛选值
        return [(None, "全部")] + [(s.value if s is Source.SQUARE else s.label, s.label) for s in Source]
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(source=self.value())
        return queryset


class QualificationFilter(admin.SimpleListFilter):
    title = "需求资质"
    parameter_name = "qualification_interest"
    def lookups(self, request, model_admin):
        q_values = Customer.objects.values_list("qualification_interest", flat=True).distinct()
        return [(None, "全部")] + [(v, v) for v in sorted(q_values) if v]
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(qualification_interest=self.value())
        return queryset


class OwnerFilter(admin.SimpleListFilter):
    """归属销售筛选——细则第一页·二"暂时做销售人员筛选、搜索筛选"."""
    title = "销售人员"
    parameter_name = "owner"

    def lookups(self, request, model_admin):
        users = User.objects.filter(
            role__in=[Role.SALES, Role.SALES_LEAD], is_active=True,
        ).order_by("real_name")
        return [(u.pk, u.real_name) for u in users]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(owner__pk=self.value())
        return queryset


class FollowUpInline(admin.TabularInline):
    """跟进记录——跟进时间可选（默认当前）、下次跟进提醒可选填."""
    model = FollowUp
    extra = 1
    fields = ("content", "created_at", "next_follow_at", "delete_link")
    readonly_fields = ("delete_link",)
    can_delete = False  # 移除"删除?"复选框列,删除改走按钮链接(delete_link)
    verbose_name_plural = "跟进记录"

    def formfield_for_dbfield(self, db_field, **kwargs):
        if db_field.name == "content":
            kwargs["widget"] = admin.widgets.AdminTextareaWidget(attrs={"rows": 2})
        return super().formfield_for_dbfield(db_field, **kwargs)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    @admin.display(description="操作")
    def delete_link(self, obj: FollowUp):
        if not obj.pk:
            return "—"
        return format_html(
            '<a href="/admin/customers/followup/{}/delete/" '
            'style="color:#DC2626;text-decoration:none;font-size:12px">删除</a>',
            obj.pk,
        )


class OwnerHistoryInline(admin.TabularInline):
    model = CustomerOwnerHistory
    extra = 0
    fields = ("seq", "transfer_display", "source_type", "source_note", "assigned_at")
    readonly_fields = fields
    can_delete = False
    verbose_name_plural = "归属变更历史（署名/撤销依据）"

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="流转", ordering="seq")
    def transfer_display(self, obj: CustomerOwnerHistory) -> str:
        """合并 from→to 为紧凑文案,撤销标记可见,避免多列挤压."""
        from_user = obj.from_user.real_name if obj.from_user else "（首次/公海）"
        to_user = obj.to_user.real_name if obj.to_user else "（释放到广场）"
        revoked = "（已撤销）" if obj.revoked_at else ""
        return f"{from_user} → {to_user}{revoked}"

    class Media:
        css = {"all": ("admin/css/owner_history.css",)}


class CustomerAttachmentInline(admin.TabularInline):
    """客户附图——细则第一页·一"附图"字段（此前模型存在但 admin 未暴露,实际传不了图）."""
    model = CustomerAttachment
    extra = 0
    fields = ("file", "uploaded_by", "uploaded_at")
    readonly_fields = ("uploaded_by", "uploaded_at")
    verbose_name_plural = "附图"

    def has_add_permission(self, request, obj=None):
        return getattr(request.user, "role", None) in FIRST_PAGE_ROLES or request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return getattr(request.user, "role", None) in FIRST_PAGE_ROLES or request.user.is_superuser


# 成交客户管理动作(status=deal 列表):转入已完结/搁置 + 转回我的客户/公司客户池 + 复制
_DEAL_ACTIONS = {"deal_to_done", "deal_to_on_hold", "deal_to_active", "deal_back_to_my", "deal_back_to_pool", "deal_copy_to_my", "deal_copy_to_pool", "assign_consultant"}

# 各角色可用动作白名单——get_actions 按此过滤,默认 delete_selected(硬删)一并不再暴露
_ROLE_ACTIONS = {
    Role.SALES: {"mark_deal", "mark_lost", "claim_from_pool", "release_to_square", "soft_delete"} | _DEAL_ACTIONS,
    Role.SALES_LEAD: {"mark_deal", "mark_lost", "claim_from_pool", "release_to_square",
                      "soft_delete", "assign_pool", "revoke_assignment"} | _DEAL_ACTIONS,
    Role.ADMIN: {"mark_deal", "mark_lost", "release_to_square",
                 "soft_delete", "assign_pool", "revoke_assignment"} | _DEAL_ACTIONS,
    Role.CONSULTANT_LEAD: {"assign_consultant"},  # 咨询主管:只分配咨询师,其他成交管理动作(已完结/搁置/转回)不给
}

# 按列表上下文区分的动作:
# 公海池列表 = 领取/调配公海 + 管理动作(标记流失/删除) + 直接成交(老板验收:公司客户池可转入成交)
# 成交客户列表(status=deal) = 转入已完结/搁置 + 转回我的客户/公司客户池 + 复制
# 普通列表 = 归属类动作(不含领取/调配公海)——与 get_queryset 的视图区分一致
_POOL_ACTIONS = {"claim_from_pool", "assign_pool", "mark_deal", "mark_lost", "soft_delete"}
_OWNED_ACTIONS = {"mark_deal", "mark_lost", "release_to_square", "revoke_assignment", "soft_delete"}

# 客户状态栏(列表每行)展示的操作:仅 新建/转入/转回(老板验收:显示哪个账号操作了什么+时间)
_STATUS_BAR_TYPES = {
    OwnerHistorySourceType.DIRECT_INPUT: "新建",
    OwnerHistorySourceType.SALES_CLAIM: "领取到我的客户",
    OwnerHistorySourceType.MANAGER_ASSIGN: "主管分配转入",
    OwnerHistorySourceType.BOSS_ASSIGN: "总经办分配转入",
    OwnerHistorySourceType.DEAL_BACK_MY: "转回我的客户",
    OwnerHistorySourceType.DEAL_BACK_POOL: "转回公司客户池",
}


class ReceiptInline(admin.TabularInline):
    """收款记录——成交客户内联(细则:收款由咨询师填写,留痕不复核)."""
    model = Receipt
    extra = 0
    fields = ("amount", "note", "received_at", "recorded_by", "created_at")
    readonly_fields = ("created_at",)
    can_delete = False
    verbose_name_plural = "收款记录"


class CostInline(admin.TabularInline):
    """支出/成本记录——成交客户内联(细则:支出咨询师申请,总经办审核通过才计入成本)."""
    model = Cost
    extra = 0
    fields = ("amount", "category", "note", "status", "recorded_by", "created_at")
    readonly_fields = ("status", "created_at")
    can_delete = False
    verbose_name_plural = "支出记录"


@admin.register(Customer)
class CustomerAdmin(RolePermissionsMixin, SimpleHistoryAdmin):
    list_display = ("summary", "source_signature", "phone_masked", "contact_name", "wechat", "qq", "intention_display", "owner", "follow_staff_display", "quote_amount", "last_follow_at", "status_bar")
    empty_value_display = "—"
    list_filter = (OwnerFilter, StatusFilter, SourceFilter, QualificationFilter, "deal_status")
    search_fields = ("company", "contact_name", "phone")

    # 需求资质多选:JSONField 存列表,表单用多选复选框
    QUALIFICATION_CHOICES = (
        ("动漫网文", "动漫网文"),
        ("表演网文", "表演网文"),
        ("音乐网文", "音乐网文"),
        ("游戏文网文", "游戏文网文"),
        ("混合网文", "混合网文"),
        ("ICP许可证", "ICP许可证"),
        ("EDI许可证", "EDI许可证"),
        ("ICPEDI", "ICPEDI（组合套餐）"),
        ("广播证", "广播电视节目制作经营许可证"),
    )

    def add_view(self, request, form_url="", extra_context=None):
        """从客户池进入添加客户:标题明确'增加 公司客户池客户'(而非笼统'增加 客户'),来源定位清晰."""
        extra_context = extra_context or {}
        if "status__exact=pool" in request.GET.get("_changelist_filters", ""):
            extra_context.setdefault("title", "增加 公司客户池客户")
        return super().add_view(request, form_url, extra_context)

    def formfield_for_dbfield(self, db_field, request=None, **kwargs):
        # 需求资质(可多选):JSONField 的 formfield 会传 encoder 参数给 MultipleChoiceField 导致 TypeError,
        # 因此不走 super() 路径,直接构造多选复选框字段
        if db_field.name == "qualification_interest":
            return forms.MultipleChoiceField(
                choices=self.QUALIFICATION_CHOICES,
                widget=forms.CheckboxSelectMultiple,
                required=False,
                label=db_field.verbose_name,
                help_text=db_field.help_text,
            )
        # 客户意向(1-5星):模型 choices 会让表单渲染为 Select 下拉(★选项),按验收改为 input 数字 1-5
        if db_field.name == "intention":
            kwargs["widget"] = forms.NumberInput(attrs={"min": 1, "max": 5, "style": "width:80px"})
        # 来源:choices 默认渲染 Select 且校验限死选项,按验收改为自由填写的 text input
        # (直接构造 CharField 绕过模型 choices 机制,否则仍是 ChoiceField 会拒绝自由文本)
        if db_field.name == "source":
            return forms.CharField(
                max_length=32,
                required=not db_field.blank,
                label=db_field.verbose_name,
                help_text=db_field.help_text,
                initial=db_field.get_default() if db_field.has_default() else None,
                widget=forms.TextInput(attrs={"maxlength": 32, "style": "width:220px"}),
            )
        return super().formfield_for_dbfield(db_field, request=request, **kwargs)
    readonly_fields = (
        "source_signature", "created_at", "updated_at", "pool_entered_at", "created_by", "square_released_by",
        "duplicate_flagged_at",
    )
    inlines = [FollowUpInline, OwnerHistoryInline, CustomerAttachmentInline, ReceiptInline, CostInline]

    fieldsets = (
        ("基本信息", {
            "fields": (
                ("company", "contact_name"),
                ("phone", "qualification_interest"),
                ("source", "quote_amount"),
                ("source_signature", "consulted_at"),
                "note",
            ),
        }),
    )

    # 新建客户页只显示建档必填/常用字段;归属(owner)自动=当前建档销售,由 save_model 赋值,不裸露手选
    add_fieldsets = (
        ("客户基本信息", {
            "fields": (
                ("company", "contact_name"),
                ("phone", "qualification_interest"),
                ("wechat", "qq"),
                ("source", "quote_amount"),
                ("intention", "consulted_at"),
                "note",
            ),
        }),
    )

    actions = [
        "mark_deal", "mark_lost",
        "claim_from_pool", "assign_pool",
        "assign_consultant",
        "release_to_square", "revoke_assignment", "soft_delete",
        "deal_to_done", "deal_to_on_hold", "deal_to_active", "deal_back_to_my",
        "deal_back_to_pool", "deal_copy_to_my", "deal_copy_to_pool",
    ]

    class Media:
        css = {"all": ("admin/css/change_form_inline_fix.css",)}

    VIEW_ROLES = FIRST_PAGE_ROLES | {Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.TECH}  # 咨询主管看全部成交(分配用);咨询师看自己跟进的;技术走建站领取
    ADD_ROLES = FIRST_PAGE_ROLES
    CHANGE_ROLES = FIRST_PAGE_ROLES | {Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.TECH}  # 咨询主管改 consultant 字段(分配);咨询师填建站/技术改进度
    DELETE_ROLES = FIRST_PAGE_ROLES

    # ---------- 表单结构 ----------

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        role = getattr(request.user, "role", None)
        # 编辑态:所有角色只显示基本信息——状态/归属/公海等系统字段由列表列与归属历史展示,
        # 流转必须走分配/释放/领取等 action,不在表单裸露
        fs = [
            ("基本信息", {
                "fields": (
                    ("company", "contact_name"),
                    ("phone", "qualification_interest"),
                    ("wechat", "qq"),
                    ("source", "quote_amount"),
                    ("intention", "consulted_at"),
                    "note",
                ),
            }),
        ]
        # 一表化(老板 09-02 拍板):成交客户(status=deal)卡片显示成交工作单+建站信息(细则第二页)
        if obj.status == CustomerStatus.DEAL:
            fs += [
                ("成交与签约", {
                    "fields": (
                        ("deal_business", "contract_entity"),
                        ("is_invoiced", "is_tax_included"),
                        ("sales", "consultant"),
                        "deal_at",
                    ),
                }),
                ("建站信息", {
                    "fields": (
                        ("site_category", "site_progress"),
                        ("tech_assigned", "site_full_name"),
                        ("site_domain_icp", "site_contact_phone"),
                        ("site_contact_address", "site_contact_email"),
                        "site_info",
                    ),
                }),
            ]
        # 咨询师:只给办证/建站所需(老板 09-02:来源/电话/QQ/微信等联系方式不展示,资质/公司名/建站信息才展示)
        if role == Role.CONSULTANT:
            keep = {"company", "qualification_interest", "deal_business", "deal_status",
                    "site_category", "site_info", "site_full_name", "site_domain_icp",
                    "site_contact_address", "site_contact_phone", "site_contact_email",
                    "site_progress", "tech_assigned"}
            filtered = []
            for name, opts in fs:
                fields = opts.get("fields", ())
                flat = []
                for f in fields:
                    if isinstance(f, (tuple, list)):
                        keep_t = tuple(x for x in f if x in keep)
                        if keep_t:
                            flat.append(keep_t)
                    elif f in keep:
                        flat.append(f)
                if flat:
                    filtered.append((name, {"fields": tuple(flat)}))
            return tuple(filtered)
        # 技术部:仅建站相关字段(细则:公司名称/成交时间/咨询师/建站类目/信息/进度)
        if role == Role.TECH:
            keep = {"company", "deal_at", "consultant", "site_category", "site_info", "site_progress"}
            filtered = []
            for name, opts in fs:
                fields = opts.get("fields", ())
                flat = []
                for f in fields:
                    if isinstance(f, (tuple, list)):
                        keep_t = tuple(x for x in f if x in keep)
                        if keep_t:
                            flat.append(keep_t)
                    elif f in keep:
                        flat.append(f)
                if flat:
                    filtered.append((name, {"fields": tuple(flat)}))
            return tuple(filtered)
        return tuple(fs)

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        role = getattr(request.user, "role", None)
        if obj is not None:
            # 编辑态:归属与状态字段一律只读,防止绕过署名/历史旁路
            base += ["owner", "status", "pool_type", "last_follow_at", "lost_reason"]
            if role == Role.CONSULTANT:
                # 咨询师:只可填建站信息(老板:建站信息由分配到咨询填写);其余全只读
                editable = {"site_category", "site_info", "site_full_name", "site_domain_icp",
                            "site_contact_address", "site_contact_phone", "site_contact_email"}
                ro = [f.name for f in Customer._meta.fields
                      if f.name not in editable and f.name not in ("id",)]
                return base + ro
            if role == Role.CONSULTANT_LEAD:
                # 咨询主管:只可改 consultant(分配咨询师);其余全只读
                ro = [f.name for f in Customer._meta.fields
                      if f.name != "consultant" and f.name not in ("id",)]
                return base + ro
            if role == Role.TECH:
                # 技术部:只可改 site_progress(领取后更新进度);其余全只读
                ro = [f.name for f in Customer._meta.fields
                      if f.name != "site_progress" and f.name not in ("id",)]
                return base + ro
        return base

    def get_actions(self, request):
        actions = super().get_actions(request)
        allowed = _ROLE_ACTIONS.get(getattr(request.user, "role", None), set())
        # 列表上下文:GET 参数为主;POST 动作处理时 Django 不还原 GET,
        # 需从动作表单隐藏字段 _changelist_filters 还原列表上下文,否则成交动作会被上下文过滤挡掉
        ctx = request.GET.get("status__exact")
        if not ctx and request.method == "POST":
            for pair in request.POST.get("_changelist_filters", "").split("&"):
                if pair.startswith("status__exact="):
                    ctx = pair.split("=", 1)[1]
                    break
        # 用 &(新集合)而非 &=(原地交集)——_ROLE_ACTIONS 是模块级可变集合,&= 会把它改坏
        if ctx == str(CustomerStatus.POOL):
            allowed = allowed & _POOL_ACTIONS
        elif ctx == str(CustomerStatus.DEAL):
            allowed = allowed & _DEAL_ACTIONS
        else:
            allowed = allowed & _OWNED_ACTIONS
        return {name: fn for name, fn in actions.items() if name in allowed}

    def _can_modify_pool(self, request, obj):
        """公海客户 修改/删除 权限:仅 建档人/释放人/其组主管/总经办(老板验收);非公海客户按角色(get_queryset 已限制可见)."""
        if obj.status != CustomerStatus.POOL:
            return True
        role = getattr(request.user, "role", None)
        if role == Role.ADMIN:
            return True
        if request.user.pk in (obj.created_by_id, obj.square_released_by_id):
            return True
        if role == Role.SALES_LEAD:
            team = getattr(request.user, "team", None)
            if team:
                return User.objects.filter(
                    pk__in=[obj.created_by_id, obj.square_released_by_id], team=team
                ).exists()
        return False

    def has_change_permission(self, request, obj=None):
        base = super().has_change_permission(request, obj)
        if not base:
            return False
        if obj is None:
            return True
        return self._can_modify_pool(request, obj)

    def has_delete_permission(self, request, obj=None):
        base = super().has_delete_permission(request, obj)
        if not base:
            return False
        if obj is None:
            return True
        return self._can_modify_pool(request, obj)

    def _scope_delete_queryset(self, request, queryset):
        """软删作用域:普通客户按归属(get_queryset 已限制可见);公海客户仅 建档人/释放人/其组主管/总经办 可删."""
        role = getattr(request.user, "role", None)
        if role == Role.ADMIN:
            return queryset
        user = request.user
        pool_self = Q(status=CustomerStatus.POOL, created_by=user) | Q(
            status=CustomerStatus.POOL, square_released_by=user
        )
        if role == Role.SALES:
            return queryset.filter(Q(owner=user) | pool_self)
        if role == Role.SALES_LEAD:
            team = getattr(user, "team", None)
            team_q = Q(owner__team=team) | Q(owner=user) if team else Q(owner=user)
            if team:
                pool_team = Q(status=CustomerStatus.POOL) & (
                    Q(created_by__team=team)
                    | Q(square_released_by__team=team)
                    | Q(created_by=user)
                    | Q(square_released_by=user)
                )
            else:
                pool_team = pool_self
            return queryset.filter(team_q | pool_team)
        return queryset.none()

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        role = getattr(user, "role", None)
        # 对象级视图(查看/修改/删除单条)与列表共用 get_queryset;公海池点开单条的 change 链接不带 status=pool 参数,
        # 若无兼容处理,公海客户(无 owner)会被普通分支过滤掉 → 404「客户不存在」,故单条视图对销售序列放开公海客户
        is_object_view = bool(
            request.resolver_match
            and request.resolver_match.url_name.endswith(("change", "delete", "view"))
        )
        if role == Role.SALES:
            # 区分视图:公海池入口(URL status=pool)/成交客户入口(URL status=deal)/普通列表(仅自己名下)
            ctx = request.GET.get("status__exact")
            if ctx == str(CustomerStatus.POOL):
                return qs.filter(status=CustomerStatus.POOL)
            if ctx == str(CustomerStatus.DEAL):
                return qs.filter(status=CustomerStatus.DEAL, owner=user)
            if is_object_view:
                return qs.filter(Q(owner=user) | Q(status=CustomerStatus.POOL))
            return qs.filter(owner=user)
        if role == Role.SALES_LEAD:
            # 区分视图:公海池入口(URL status=pool)看全部公海客户(细则五所有人员可见);普通列表看组员+自己
            ctx = request.GET.get("status__exact")
            if ctx == str(CustomerStatus.POOL):
                return qs.filter(status=CustomerStatus.POOL)
            team = getattr(user, "team", None)
            team_q = Q(owner__team=team) | Q(owner=user) if team else Q(owner=user)
            if ctx == str(CustomerStatus.DEAL):
                return qs.filter(status=CustomerStatus.DEAL).filter(team_q)
            if is_object_view:
                return qs.filter(team_q | Q(status=CustomerStatus.POOL))
            return qs.filter(team_q)
        if role == Role.ADMIN:
            return qs
        # 咨询主管:看全部客户(与总经办同视角,用于"待分配单子"分配咨询师);不能释放(释放动作已限 SALES/SALES_LEAD/ADMIN)
        if role == Role.CONSULTANT_LEAD:
            return qs
        # 咨询师:只看自己跟进的成交客户(一表化后 consultant 字段直挂客户;联系方式对其隐藏见 fieldsets)
        if role == Role.CONSULTANT:
            base_deal = qs.filter(status=CustomerStatus.DEAL, consultant=user)
            if is_object_view:
                return base_deal
            if request.GET.get("status__exact") == str(CustomerStatus.DEAL):
                return base_deal
            return qs.none()
        # 技术部:建站任务池(需建站未承接)+我承接的;字段按细则仅建站相关(fieldsets 限定)
        if role == Role.TECH:
            claimable = qs.filter(status=CustomerStatus.DEAL, tech_assigned__isnull=True)
            mine_q = qs.filter(status=CustomerStatus.DEAL, tech_assigned=user)
            return (claimable | mine_q).distinct()
        # 财务不看客户表(财务搁置由总经办代行)
        return qs.none()

    def get_changelist_instance(self, request):
        cl = super().get_changelist_instance(request)
        _request_local.request = request
        return cl

    @admin.display(description="意愿度", ordering="intention")
    def intention_display(self, obj):
        """客户意向(1-5星):★ 星级展示,列表一眼可见."""
        if not obj.intention:
            return "—"
        return format_html('<span style="color:#EAB308;letter-spacing:1px">{}</span>', "★" * obj.intention)

    @admin.display(description="状态栏(客户意向/最近操作)")
    def status_bar(self, obj):
        """客户状态栏:客户意向(x星) + 最近一条 新建/转入/转回 操作(账号+操作+时间).
        无归属历史的老数据(建档时未写 OwnerHistory)回退用 created_by/created_at 显示「新建」,保证每行都有内容."""
        cells = []
        if obj.intention:
            cells.append(format_html('<span style="color:#B45309;font-weight:700">{}</span>', f"{obj.intention}星"))
        h = obj.owner_history.filter(source_type__in=_STATUS_BAR_TYPES).order_by("-seq").first()
        if h:
            who = h.operator or h.to_user
            who_name = "系统"
            if who:
                who_name = getattr(who, "real_name", None) or who.username
            op = _STATUS_BAR_TYPES.get(h.source_type, str(h.source_type))
            when = h.assigned_at.strftime("%m-%d %H:%M") if h.assigned_at else ""
        elif obj.created_by_id and obj.created_at:
            # 回退:老数据无归属历史 → 用建档信息显示「新建」
            who_name = getattr(obj.created_by, "real_name", None) or (obj.created_by.username if obj.created_by else "系统")
            op = "新建"
            when = obj.created_at.strftime("%m-%d %H:%M")
        else:
            who_name, op, when = "", "", ""
        if when:
            cells.append(format_html('<span style="font-size:12px;color:#475569">{}</span>', f"{who_name} {op} {when}"))
        if not cells:
            return "—"
        if len(cells) == 1:
            return cells[0]
        return format_html("{} {}", cells[0], cells[1])

    # ---------- 保存与软删 ----------

    def save_model(self, request, obj, form, change):
        # 注意顺序:必须先落库拿到 pk,再写归属历史（旧代码反着来,新增客户直接 500）
        if not change:
            obj.created_by = request.user
            # 新增客户归属默认 = 当前建档销售（细则:哪个销售上传自动署名,客户归其名下）
            if not obj.owner and getattr(request.user, "role", None) in (Role.SALES, Role.SALES_LEAD):
                obj.owner = request.user
        super().save_model(request, obj, form, change)
        # 提交日志（审计）:记录谁在何时提交/修改了什么信息,后台可查
        try:
            OperationLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="新增" if not change else "修改",
                target=f"客户 {obj.company}",
                detail=(
                    f"公司:{obj.company} 联系人:{obj.contact_name} 电话:{obj.phone} "
                    f"资质:{obj.qualification_interest or ''}"
                ),
            )
        except Exception:
            pass  # 日志失败不影响主流程
        if not change:
            CustomerOwnerHistory.objects.create(
                customer=obj, from_user=None, to_user=obj.owner or request.user,
                source_type=OwnerHistorySourceType.DIRECT_INPUT,
                operator=request.user, seq=1,
            )
        # 撞单提醒（细则第一页·六）：软查重不拦截,录入后做标识并送总经办信息箱
        duplicates = obj.find_duplicates()
        if duplicates.exists():
            now = timezone.now()
            if not obj.duplicate_flagged_at:
                Customer.objects.filter(pk=obj.pk).update(duplicate_flagged_at=now)
                obj.duplicate_flagged_at = now
            dup_names = "、".join(d.company for d in duplicates[:3])
            self.message_user(
                request,
                f"与同事录入相同信息：{dup_names}（本条已录入并做标识，请与公司总经办联系）",
                level=messages.WARNING,
            )
            admins = User.objects.filter(role=Role.ADMIN, is_active=True)
            try:
                notify(
                    category=NotificationCategory.DUPLICATE,
                    importance=Importance.HIGH,
                    recipients=list(admins),
                    title="撞单提醒",
                    content=f"客户「{obj.company}」与「{dup_names}」疑似重复（录入人:{request.user.real_name}），请核查归属。",
                    link="/admin/customers/customer/",
                    actor=request.user,
                    entity_type="customer",
                    entity_id=obj.pk,
                )
            except Exception:
                pass

    def save_formset(self, request, form, formset, change):
        """补齐 inline 署名;跟进记录落库后联动客户 last_follow_at（30天掉公海的数据源）."""
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instances:
            if isinstance(obj, CustomerAttachment) and not obj.uploaded_by_id:
                obj.uploaded_by = request.user
            obj.save()
        formset.save_m2m()
        customer = form.instance
        latest_follow = customer.follow_ups.order_by("-created_at").first()
        if latest_follow and (not customer.last_follow_at or latest_follow.created_at > customer.last_follow_at):
            Customer.objects.filter(pk=customer.pk).update(last_follow_at=latest_follow.created_at)

    def delete_model(self, request, obj):
        # 单个删除也走软删（细则第一页·七:删除的客户信息要能在回收站查看）
        obj.deleted_at = timezone.now()
        obj.deleted_by = request.user if request.user.is_authenticated else None
        obj.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
        # 留痕:删除操作记录日志
        try:
            OperationLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="删除",
                target=f"客户 {obj.company}",
                detail="软删进回收站",
            )
        except Exception:
            pass

    def delete_queryset(self, request, queryset):
        # 批量删除兜底走软删,记录删除人(回收站按角色分权依据)
        queryset.update(
            deleted_at=timezone.now(), updated_at=timezone.now(),
            deleted_by=request.user if request.user.is_authenticated else None,
        )
        # 留痕:批量删除记录日志
        try:
            OperationLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="删除",
                target="客户（批量）",
                detail=f"{queryset.count()} 个客户软删进回收站",
            )
        except Exception:
            pass

    def delete_view(self, request, object_id, extra_context=None):
        """覆盖默认删除视图——客户一律软删进回收站,不受成交项目 PROTECT 外键阻止.

        背景:Django 默认 delete_view 会调 get_deleted_objects 检查外键保护,
        客户已成交(有 Project,on_delete=PROTECT)时返回"无法删除"页,连软删都不走,
        导致"删了回收站看不到"。软删只是设 deleted_at、不真正删行,不违反 FK,
        因此跳过受保护检查,直接确认后软删。
        """
        from django.core.exceptions import PermissionDenied
        from django.http import HttpResponseRedirect, Http404
        from django.urls import reverse

        obj = self.get_object(request, object_id)
        if obj is None:
            raise Http404
        if not self.has_delete_permission(request, obj):
            raise PermissionDenied

        if request.method == "POST":
            self.delete_model(request, obj)
            self.message_user(request, f"客户「{obj.company}」已删除(进入回收站,可恢复)", messages.SUCCESS)
            return HttpResponseRedirect(reverse("admin:customers_customer_changelist"))

        # GET:渲染确认页,deleted_objects 置空跳过 PROTECT 检查,总是可软删
        context = {
            **self.admin_site.each_context(request),
            "title": f"删除客户: {obj.company}",
            "object_name": "客户",
            "object": obj,
            "deleted_objects": [],
            "model_count": {},
            "queryset": [obj],
            "opts": self.model._meta,
        }
        if extra_context:
            context.update(extra_context)
        return TemplateResponse(request, "admin/delete_confirmation.html", context)

    # ---------- 建站领取(一表化:成交客户卡承接)——技术/总经办 ----------

    def claim_site_view(self, request, object_id):
        """技术领取建站(细则:暂由技术同事自行协商搭建→领取制):记录承接人+通知咨询+留痕."""
        from django.shortcuts import redirect
        from django.contrib import messages as msgs
        role = getattr(request.user, "role", None)
        if role not in (Role.TECH, Role.ADMIN):
            self.message_user(request, "仅技术/总经办可领取建站任务", msgs.ERROR)
            return redirect("/admin/tech-workbench/")
        customer = Customer.objects.filter(
            pk=object_id, status=CustomerStatus.DEAL, tech_assigned__isnull=True
        ).first()
        if not customer:
            self.message_user(request, "任务不存在或已被领取", msgs.ERROR)
            return redirect("/admin/tech-workbench/")
        # 承接=开始搭建:自动更新进度为进行中(用户:承接后不该还是待开始)
        Customer.objects.filter(pk=customer.pk).update(
            tech_assigned=request.user, site_progress="in_progress"
        )
        try:
            if customer.consultant_id:
                notify(
                    category=NotificationCategory.SITE_TAKEN,
                    importance=Importance.MEDIUM,
                    recipients=customer.consultant,
                    title="建站任务已承接",
                    content=f"「{customer.company}」建站任务由 {request.user.real_name} 领取,后续建站事宜请联系该技术。",
                    link=f"/admin/customers/customer/{customer.pk}/change/",
                    actor=request.user,
                    entity_type="customer",
                    entity_id=customer.pk,
                )
            OperationLog.objects.create(
                user=request.user, action="承接建站",
                target=f"客户 {customer.company}",
                detail=f"技术 {request.user.real_name} 领取建站任务",
            )
        except Exception:
            pass
        self.message_user(request, f"已领取建站任务:{customer.company},已通知咨询", msgs.SUCCESS)
        return redirect("/admin/tech-workbench/")

    # ---------- 撞单预检（录入前弹窗的数据接口） ----------

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "check-duplicates/",
                self.admin_site.admin_view(self.check_duplicates_view),
                name="customers_customer_check_duplicates",
            ),
            path(
                "<path:object_id>/claim/",
                self.admin_site.admin_view(self.claim_site_view),
                name="customers_customer_claim_site",
            ),
        ]
        return custom + urls

    def check_duplicates_view(self, request):
        """按公司名/联系人/电话做录入前查重,返回 JSON 供前端弹窗展示."""
        conditions = Q()
        has_condition = False
        # 尝试提交日志:即使被弹窗拦截,后台也要能追溯'谁尝试提交了什么'
        try:
            OperationLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="尝试提交",
                target="客户 查重",
                detail=(
                    f"公司:{request.GET.get('company','')} "
                    f"联系人:{request.GET.get('contact','')} "
                    f"电话:{request.GET.get('phone','')}"
                ),
            )
        except Exception:
            pass  # 日志失败不影响查重
        # 录入前查重只认高置信度(与 find_duplicates SSOT 统一):公司名/电话精确相同才提示;泛称联系人(王总)无唯一性,不触发
        for field, value in (
            ("company", request.GET.get("company", "")),
            ("phone", request.GET.get("phone", "")),
        ):
            value = value.strip()
            if value:
                conditions |= Q(**{f"{field}__iexact": value})
                has_condition = True
        if not has_condition:
            return JsonResponse({"duplicates": []})
        qs = Customer.objects.filter(conditions)
        exclude_pk = request.GET.get("exclude")
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        data = []
        for c in qs.select_related("owner", "created_by")[:5]:
            # 计算与当前录入哪项信息相同(公司名/联系人/电话),标明'相同在哪'
            match = []
            company_q = request.GET.get("company", "").strip()
            contact_q = request.GET.get("contact", "").strip()
            phone_q = request.GET.get("phone", "").strip()
            if company_q and c.company and c.company.lower() == company_q.lower():
                match.append("公司名")
            if contact_q and c.contact_name and c.contact_name.lower() == contact_q.lower():
                match.append("联系人")
            if phone_q and c.phone and c.phone == phone_q:
                match.append("电话")
            data.append({
                "company": c.company,
                "owner": c.owner.real_name if c.owner else "公海/无归属",
                # 录入人:标明'哪个同事'录的(客户可能在公海,owner为空,但created_by是录入者)
                "created_by": c.created_by.real_name if c.created_by else "未知",
                # 相同项:让用户知道'相同在哪'(公司名/联系人/电话)
                "match_fields": match or ["信息"],
            })
        return JsonResponse({"duplicates": data})

    # ---------- 列表展示 ----------

    def summary(self, obj: Customer) -> str:
        # 需求资质已改为 JSONField(list),多资质用顿号连接展示
        qual_list = obj.qualification_interest or []
        qual = "、".join(str(q).replace("（组合套餐）", "") for q in qual_list) or "未填"
        badges = format_html(
            "<span style='padding:1px 7px;border-radius:6px;background:#E8EDFB;"
            "color:#3B5098;font-size:11px'>{}</span>"
            " <span style='padding:1px 8px;border-radius:6px;background:#E8F5E9;"
            "color:#2E7D32;font-size:11px'>{}</span>",
            qual, obj.get_status_display(),
        )
        # 成交客户子状态徽标(老板验收:列表可见 进行中/搁置/已完结)——红绿灯配色
        if obj.deal_status:
            deal_style = {
                DealStatus.ACTIVE: ("进行中", "#DCFCE7", "#15803D"),
                DealStatus.ON_HOLD: ("搁置", "#FEF3C7", "#B45309"),
                DealStatus.DONE: ("已完结", "#FEE2E2", "#B91C1C"),
            }.get(obj.deal_status)
            if deal_style:
                label, bg, fg = deal_style
                badges += format_html(
                    " <span style='padding:1px 8px;border-radius:6px;background:{};"
                    "color:{};font-size:11px'>{}</span>",
                    bg, fg, label,
                )
        if obj.duplicate_flagged_at:
            badges += format_html(
                " <span style='padding:1px 8px;border-radius:6px;background:#FDE8E8;"
                "color:#C0392B;font-size:11px' title='{}'>撞单</span>",
                obj.duplicate_flagged_at.strftime("%Y-%m-%d %H:%M"),
            )
        return format_html("{}  {}", obj.company, badges)
    summary.short_description = "公司 / 业务 / 进度"  # type: ignore[attr-defined]
    summary.admin_order_field = "company"  # type: ignore[attr-defined]

    @admin.display(description="来源（含广场署名）")
    def source_signature(self, obj: Customer) -> str:
        return obj.source_label
    source_signature.short_description = "来源"  # type: ignore[attr-defined]

    def phone_masked(self, obj: Customer) -> str:
        phone = obj.phone
        if obj.status == CustomerStatus.POOL and len(phone) >= 7:
            request = getattr(_request_local, "request", None)
            viewer_role = getattr(getattr(request, "user", None), "role", None)
            if viewer_role != Role.ADMIN:
                return f"{phone[:3]}****{phone[-4:]}"
        return phone
    phone_masked.short_description = "电话"  # type: ignore[attr-defined]

    # ---------- 状态与流转 Actions ----------

    @admin.action(description="转入成交")
    def mark_deal(self, request, queryset):
        """成交：弹窗填写已收金额/签约主体/备注 → 状态改 DEAL + 创建 Project + 通知嘉茵分配咨询师."""
        from apps.projects.models import Project
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "仅销售序列/总经办可操作成交", messages.ERROR)
            return
        candidates = list(queryset.filter(
            status__in=[CustomerStatus.LEAD, CustomerStatus.FOLLOWING, CustomerStatus.POOL]
        ))
        if not candidates:
            self.message_user(request, "所选客户无可转成交的客户（需为线索/跟进/公司客户池状态）", messages.WARNING)
            return
        if "apply" in request.POST:
            received_amount = request.POST.get("received_amount", "0").strip()
            contract_entity = request.POST.get("contract_entity", "").strip()
            deal_note = request.POST.get("deal_note", "").strip()
            try:
                received_amount = float(received_amount)
            except (ValueError, TypeError):
                received_amount = 0
            now = timezone.now()
            cnt = 0
            for customer in candidates:
                claimed_from_pool = customer.status == CustomerStatus.POOL
                customer.status = CustomerStatus.DEAL
                customer.deal_status = DealStatus.ACTIVE
                customer.updated_at = now
                update_fields = ["status", "deal_status", "updated_at"]
                if contract_entity:
                    customer.contract_entity = contract_entity
                    update_fields.append("contract_entity")
                if deal_note:
                    customer.note = (customer.note + "\n" if customer.note else "") + f"[成交] {deal_note}"
                    update_fields.append("note")
                if claimed_from_pool and customer.owner_id is None:
                    customer.owner = request.user
                    customer.pool_type = None
                    CustomerOwnerHistory.objects.create(
                        customer=customer, from_user=None, to_user=request.user,
                        source_type=OwnerHistorySourceType.SALES_CLAIM, operator=request.user,
                        seq=_next_seq(customer.owner_history), source_note="公海直接成交",
                    )
                    update_fields += ["owner", "pool_type"]
                customer.save(update_fields=update_fields)
                # 已收金额 > 0 时自动创建收款记录
                if received_amount > 0:
                    Receipt.objects.create(
                        customer=customer, amount=received_amount,
                        note="成交首笔收款", recorded_by=request.user, received_at=now.date(),
                    )
                # 创建 Project(幂等)
                project, created = Project.objects.get_or_create(
                    customer=customer,
                    defaults=dict(
                        company_snapshot=customer.company,
                        contact_name_snapshot=customer.contact_name,
                        phone_snapshot=customer.phone,
                        source_snapshot=customer.source_label,
                        quote_amount=customer.quote_amount,
                        sales=customer.owner,
                        consultant=None,
                    ),
                )
                if created:
                    try:
                        leads = User.objects.filter(role=Role.CONSULTANT_LEAD, is_active=True)
                        notify(
                            category=NotificationCategory.DEAL_CONVERT,
                            importance=Importance.HIGH,
                            recipients=list(leads),
                            title="新项目待分配咨询师",
                            content=f"「{customer.company}」已成交转立项（成交人:{request.user.real_name}），请分配咨询师。",
                            link=f"/admin/projects/project/{project.pk}/change/",
                            actor=request.user,
                            entity_type="project",
                            entity_id=project.pk,
                        )
                    except Exception:
                        pass
                cnt += 1
            self.message_user(request, f"{cnt} 个客户已成交,已创建收款记录,等待嘉茵分配咨询师。", messages.SUCCESS)
            return
        # 弹窗:填写已收金额/签约主体/备注
        context = dict(
            self.admin_site.each_context(request),
            title="转入成交",
            action_checkbox_name=admin.helpers.ACTION_CHECKBOX_NAME,
            queryset=candidates,
        )
        return TemplateResponse(request, "admin/customers/mark_deal.html", context)

    # ---------- 成交客户信息管理(进行中/已完结/搁置)——老板验收新增 ----------

    def _scope_deal_queryset(self, request, queryset):
        """成交客户动作作用域:销售只看自己名下,主管看本组+自己,总经办全部."""
        role = getattr(request.user, "role", None)
        if role == Role.SALES:
            return queryset.filter(owner=request.user)
        if role == Role.SALES_LEAD:
            team = getattr(request.user, "team", None)
            if team:
                return queryset.filter(Q(owner__team=team) | Q(owner=request.user))
            return queryset.filter(owner=request.user)
        return queryset

    @admin.action(description="转入已完结")
    def deal_to_done(self, request, queryset):
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "无权限执行该操作", messages.ERROR)
            return
        updated = self._scope_deal_queryset(request, queryset).filter(
            status=CustomerStatus.DEAL
        ).update(deal_status=DealStatus.DONE, updated_at=timezone.now())
        self.message_user(request, f"{updated} 个成交客户已转入已完结", messages.SUCCESS)

    @admin.action(description="转入搁置")
    def deal_to_on_hold(self, request, queryset):
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "无权限执行该操作", messages.ERROR)
            return
        updated = self._scope_deal_queryset(request, queryset).filter(
            status=CustomerStatus.DEAL
        ).update(deal_status=DealStatus.ON_HOLD, updated_at=timezone.now())
        self.message_user(request, f"{updated} 个成交客户已转入搁置", messages.SUCCESS)

    @admin.action(description="转回进行中的客户")
    def deal_to_active(self, request, queryset):
        """搁置 → 进行中:老板规范「搁置的客户:转回进行中的客户」(2026-08-30 命名对齐新增)."""
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "无权限执行该操作", messages.ERROR)
            return
        updated = self._scope_deal_queryset(request, queryset).filter(
            status=CustomerStatus.DEAL, deal_status=DealStatus.ON_HOLD
        ).update(deal_status=DealStatus.ACTIVE, updated_at=timezone.now())
        self.message_user(request, f"{updated} 个搁置客户已转回进行中", messages.SUCCESS)

    @admin.action(description="转回我的客户")
    def deal_back_to_my(self, request, queryset):
        """成交退回:DEAL → FOLLOWING(保留归属销售),成交子状态清空,记归属历史(状态栏「转回」)."""
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "无权限执行该操作", messages.ERROR)
            return
        updated = 0
        for c in self._scope_deal_queryset(request, queryset).filter(status=CustomerStatus.DEAL):
            c.status = CustomerStatus.FOLLOWING
            c.deal_status = None
            c.updated_at = timezone.now()
            c.save(update_fields=["status", "deal_status", "updated_at"])
            CustomerOwnerHistory.objects.create(
                customer=c, from_user=None, to_user=c.owner, operator=request.user,
                source_type=OwnerHistorySourceType.DEAL_BACK_MY,
                seq=_next_seq(c.owner_history), source_note="成交转回我的客户",
            )
            updated += 1
        self.message_user(request, f"{updated} 个成交客户已转回我的客户", messages.SUCCESS)

    @admin.action(description="转回公司客户池")
    def deal_back_to_pool(self, request, queryset):
        """成交退回公海:DEAL → POOL,清归属,记归属历史."""
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "无权限执行该操作", messages.ERROR)
            return
        updated = 0
        for c in self._scope_deal_queryset(request, queryset).filter(status=CustomerStatus.DEAL):
            prev_owner = c.owner
            c.status = CustomerStatus.POOL
            c.deal_status = None
            c.owner = None
            c.pool_type = PoolType.SQUARE
            c.pool_entered_at = timezone.now()
            c.updated_at = timezone.now()
            c.save(update_fields=["status", "deal_status", "owner", "pool_type", "pool_entered_at", "updated_at"])
            CustomerOwnerHistory.objects.create(
                customer=c, from_user=prev_owner, to_user=None, operator=request.user,
                source_type=OwnerHistorySourceType.DEAL_BACK_POOL,
                seq=_next_seq(c.owner_history), source_note="成交转回公司客户池",
            )
            updated += 1
        self.message_user(request, f"{updated} 个成交客户已转回公司客户池", messages.SUCCESS)

    @admin.action(description="复制到我的客户")
    def deal_copy_to_my(self, request, queryset):
        """已完结客户复制成新客户(跟进中),归属操作人,记新建历史."""
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "无权限执行该操作", messages.ERROR)
            return
        updated = 0
        for c in self._scope_deal_queryset(request, queryset).filter(
            status=CustomerStatus.DEAL, deal_status=DealStatus.DONE
        ):
            nc = Customer.objects.create(
                company=c.company, contact_name=c.contact_name, phone=c.phone,
                qualification_interest=c.qualification_interest, source=c.source,
                quote_amount=c.quote_amount, note=c.note, consulted_at=c.consulted_at,
                status=CustomerStatus.FOLLOWING, owner=request.user, created_by=request.user,
            )
            CustomerOwnerHistory.objects.create(
                customer=nc, from_user=None, to_user=request.user,
                source_type=OwnerHistorySourceType.DIRECT_INPUT, operator=request.user,
                seq=1, source_note="从已完结成交客户复制",
            )
            updated += 1
        self.message_user(request, f"{updated} 个已完结客户已复制到我的客户", messages.SUCCESS)

    @admin.action(description="复制到公司客户池")
    def deal_copy_to_pool(self, request, queryset):
        """已完结客户复制成公海新客户."""
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "无权限执行该操作", messages.ERROR)
            return
        updated = 0
        for c in self._scope_deal_queryset(request, queryset).filter(
            status=CustomerStatus.DEAL, deal_status=DealStatus.DONE
        ):
            nc = Customer.objects.create(
                company=c.company, contact_name=c.contact_name, phone=c.phone,
                qualification_interest=c.qualification_interest, source=c.source,
                quote_amount=c.quote_amount, note=c.note, consulted_at=c.consulted_at,
                status=CustomerStatus.POOL, owner=None, pool_type=PoolType.SQUARE,
                created_by=request.user,
            )
            CustomerOwnerHistory.objects.create(
                customer=nc, from_user=None, to_user=None,
                source_type=OwnerHistorySourceType.SQUARE, operator=request.user,
                seq=1, source_note="从已完结成交客户复制",
            )
            updated += 1
        self.message_user(request, f"{updated} 个已完结客户已复制到公司客户池", messages.SUCCESS)

    @admin.action(description="标记流失")
    def mark_lost(self, request, queryset):
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "无权限执行该操作", messages.ERROR)
            return
        if role == Role.SALES:
            queryset = queryset.filter(owner=request.user)
        updated = queryset.filter(status__in=[CustomerStatus.FOLLOWING, CustomerStatus.POOL]).update(
            status=CustomerStatus.LOST, updated_at=timezone.now()
        )
        # 公海流转:标记流失 → 知会销售主管/总经办
        try:
            leads = User.objects.filter(role=Role.SALES_LEAD, is_active=True)
            admins = User.objects.filter(role=Role.ADMIN, is_active=True)
            pool_recipients = list({u.pk: u for u in list(leads) + list(admins)}.values())
            notify(
                category=NotificationCategory.POOL_FLOW,
                importance=Importance.MEDIUM,
                recipients=pool_recipients,
                title="客户标记流失",
                content=f"{request.user.real_name} 将 {updated} 个客户标记为流失。",
                link="/admin/customers/customer/",
                actor=request.user,
            )
        except Exception:
            pass
        self.message_user(request, f"{updated} 个客户已标记流失", messages.SUCCESS)

    @admin.action(description="删除（进入回收站）")
    def soft_delete(self, request, queryset):
        # 权限:公海客户仅 建档人/释放人/其组主管/总经办 可删(老板验收),普通客户按归属
        updated = self._scope_delete_queryset(request, queryset).update(
            deleted_at=timezone.now(), updated_at=timezone.now(),
            deleted_by=request.user if request.user.is_authenticated else None,
        )
        # 留痕:软删操作记录日志
        try:
            OperationLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="删除",
                target="客户（批量）",
                detail=f"{updated} 个客户软删进回收站",
            )
        except Exception:
            pass
        self.message_user(
            request, f"{updated} 个客户已移入回收站（可查看/恢复）", messages.SUCCESS,
        )

    @admin.action(description="领取到我的客户")
    def claim_from_pool(self, request, queryset):
        if getattr(request.user, "role", None) not in (Role.SALES, Role.SALES_LEAD):
            self.message_user(request, "仅销售/销售主管可领取公海客户", messages.ERROR)
            return
        now = timezone.now()
        cnt = 0
        for customer in queryset.filter(status=CustomerStatus.POOL):
            releaser_name = (
                customer.square_released_by.real_name
                if customer.pool_type == PoolType.SQUARE and customer.square_released_by
                else ""
            )
            customer.status = CustomerStatus.FOLLOWING
            customer.owner = request.user
            customer.pool_entered_at = None
            customer.pool_type = None
            customer.last_follow_at = now
            customer.updated_at = now
            customer.save()
            CustomerOwnerHistory.objects.create(
                customer=customer, from_user=None, to_user=request.user,
                source_type=(OwnerHistorySourceType.SQUARE if releaser_name else OwnerHistorySourceType.SALES_CLAIM),
                source_note=releaser_name,
                operator=request.user, seq=_next_seq(customer.owner_history),
            )
            cnt += 1
        self.message_user(request, f"已领取 {cnt} 个公海客户", messages.SUCCESS)

    @admin.action(description="分配客户（指定人员+理由弹窗）")
    def assign_pool(self, request, queryset):
        """细则第一页·四:主管/总经办分配自己管辖池的客户（不限公海状态）给指定人员."""
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "仅销售主管/总经办可分配客户", messages.ERROR)
            return None
        candidates = queryset.exclude(status=CustomerStatus.DEAL)
        if "apply" in request.POST:
            new_owner_id = request.POST.get("new_owner")
            reason = request.POST.get("reason", "").strip()
            if not new_owner_id or not reason:
                self.message_user(request, "请选择目标销售并填写调配理由", messages.ERROR)
                return None
            from apps.accounts.models import Role as RoleEnum
            new_owner = User.objects.filter(
                id=new_owner_id, is_active=True, role__in=[RoleEnum.SALES, RoleEnum.SALES_LEAD],
            ).first()
            if new_owner is None:
                self.message_user(request, "目标人员无效（需为在职销售/销售主管）", messages.ERROR)
                return None
            now = timezone.now()
            source_type = (
                OwnerHistorySourceType.BOSS_ASSIGN if role == Role.ADMIN
                else OwnerHistorySourceType.MANAGER_ASSIGN
            )
            cnt = 0
            for customer in candidates:
                prev_owner = customer.owner
                customer.owner = new_owner
                if customer.status == CustomerStatus.POOL:
                    customer.pool_entered_at = None
                    customer.pool_type = None
                customer.status = CustomerStatus.FOLLOWING
                customer.updated_at = now
                customer.save()
                CustomerOwnerHistory.objects.create(
                    customer=customer, from_user=prev_owner, to_user=new_owner,
                    source_type=source_type, source_note=reason,
                    operator=request.user, seq=_next_seq(customer.owner_history),
                )
                cnt += 1
            try:
                notify(
                    category=NotificationCategory.ASSIGN_CUSTOMER,
                    importance=Importance.MEDIUM,
                    recipients=new_owner,
                    title="客户分配通知",
                    content=f"{request.user.real_name} 将 {cnt} 个客户分配给你（理由:{reason}），请及时跟进。",
                    link="/admin/customers/customer/",
                    actor=request.user,
                )
            except Exception:
                pass
            self.message_user(
                request,
                f"已将 {cnt} 个客户分配给 {new_owner.real_name}（理由: {reason}），已通知对方",
                messages.SUCCESS,
            )
            return None
        from apps.accounts.models import Role as RoleEnum
        sales_users = User.objects.filter(role__in=[RoleEnum.SALES, RoleEnum.SALES_LEAD], is_active=True)
        context = dict(
            self.admin_site.each_context(request),
            title="分配客户",
            action_checkbox_name=admin.helpers.ACTION_CHECKBOX_NAME,
            queryset=candidates,
            sales_users=sales_users,
        )
        return TemplateResponse(request, "admin/customers/assign_pool.html", context)

    @admin.action(description="分配咨询师")
    def assign_consultant(self, request, queryset):
        """咨询主管/总经办:将成交客户分配给指定咨询师跟进办证."""
        role = getattr(request.user, "role", None)
        if role not in (Role.CONSULTANT_LEAD, Role.ADMIN):
            self.message_user(request, "仅咨询主管/总经办可分配咨询师", messages.ERROR)
            return None
        candidates = queryset.filter(status=CustomerStatus.DEAL)
        if not candidates.exists():
            self.message_user(request, "所选客户中无成交客户", messages.WARNING)
            return None
        if "apply" in request.POST:
            consultant_id = request.POST.get("consultant_id")
            note = request.POST.get("note", "").strip()
            if not consultant_id:
                self.message_user(request, "请选择咨询师", messages.ERROR)
                return None
            consultant_user = User.objects.filter(
                id=consultant_id, is_active=True, role=Role.CONSULTANT,
            ).first()
            if consultant_user is None:
                self.message_user(request, "目标咨询师无效（需为在职咨询师）", messages.ERROR)
                return None
            now = timezone.now()
            cnt = 0
            for customer in candidates:
                prev = customer.consultant
                customer.consultant = consultant_user
                customer.updated_at = now
                customer.save(update_fields=["consultant", "updated_at"])
                CustomerOwnerHistory.objects.create(
                    customer=customer, from_user=prev, to_user=consultant_user,
                    source_type=OwnerHistorySourceType.MANAGER_ASSIGN,
                    source_note=f"咨询主管分配咨询师{(' — ' + note) if note else ''}",
                    operator=request.user, seq=_next_seq(customer.owner_history),
                )
                cnt += 1
            try:
                notify(
                    category=NotificationCategory.ASSIGN_CUSTOMER,
                    importance=Importance.HIGH,
                    recipients=consultant_user,
                    title="新客户待跟进",
                    content=f"{request.user.real_name} 将 {cnt} 个成交客户分配给你（{note or '办证跟进'}），请在「我的客户」中查看。",
                    link="/admin/customers/customer/?status__exact=deal",
                    actor=request.user,
                )
            except Exception:
                pass
            self.message_user(request, f"已将 {cnt} 个客户分配给咨询师 {consultant_user.real_name}", messages.SUCCESS)
            return None
        consultant_users = User.objects.filter(role=Role.CONSULTANT, is_active=True)
        context = dict(
            self.admin_site.each_context(request),
            title="分配咨询师",
            action_checkbox_name=admin.helpers.ACTION_CHECKBOX_NAME,
            queryset=candidates,
            consultant_users=consultant_users,
        )
        return TemplateResponse(request, "admin/customers/assign_consultant.html", context)

    @admin.action(description="释放到公司客户池")
    def release_to_square(self, request, queryset):
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "无权限执行该操作", messages.ERROR)
            return None
        if role == Role.SALES:
            queryset = queryset.filter(owner=request.user)
        if "apply" in request.POST:
            reason = request.POST.get("reason", "").strip()
            if not reason:
                self.message_user(request, "请填写释放理由", messages.ERROR)
                return None
            now = timezone.now()
            cnt = 0
            for customer in queryset.filter(status__in=[CustomerStatus.LEAD, CustomerStatus.FOLLOWING]):
                customer.status = CustomerStatus.POOL
                customer.pool_type = PoolType.SQUARE
                customer.square_released_by = request.user
                # 来源署名展示由 source=SQUARE + square_released_by 组合承担,
                # 不再直接改写 source 字符串（旧写法会写爆 choices/max_length）
                customer.source = Source.SQUARE
                customer.owner = None
                customer.pool_entered_at = now
                customer.updated_at = now
                customer.save()
                CustomerOwnerHistory.objects.create(
                    customer=customer, from_user=request.user, to_user=None,
                    source_type=OwnerHistorySourceType.SQUARE, operator=request.user,
                    seq=_next_seq(customer.owner_history), source_note=reason,
                )
                cnt += 1
            # 公海流转:释放到客户池广场 → 知会销售主管/总经办
            try:
                leads = User.objects.filter(role=Role.SALES_LEAD, is_active=True)
                admins = User.objects.filter(role=Role.ADMIN, is_active=True)
                pool_recipients = list({u.pk: u for u in list(leads) + list(admins)}.values())
                notify(
                    category=NotificationCategory.POOL_FLOW,
                    importance=Importance.LOW,
                    recipients=pool_recipients,
                    title="客户释放到公司客户池",
                    content=f"{request.user.real_name} 将 {cnt} 个客户释放到公司客户池（理由:{reason}）。",
                    link="/admin/customers/customer/?status__exact=pool",
                    actor=request.user,
                )
            except Exception:
                pass
            self.message_user(request, f"已释放 {cnt} 个客户到公司客户池（理由: {reason}）", messages.SUCCESS)
            return None
        candidates = queryset.filter(status__in=[CustomerStatus.LEAD, CustomerStatus.FOLLOWING])
        context = dict(
            self.admin_site.each_context(request),
            title="释放到公司客户池",
            action_checkbox_name=admin.helpers.ACTION_CHECKBOX_NAME,
            queryset=candidates,
        )
        return TemplateResponse(request, "admin/customers/release_to_square.html", context)

    @admin.action(description="撤销分配（回退到上一持有人）")
    def revoke_assignment(self, request, queryset):
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "仅销售主管/总经办可撤销分配", messages.ERROR)
            return
        cnt, skipped = 0, 0
        now = timezone.now()
        for customer in queryset:
            if customer.status == CustomerStatus.DEAL:
                skipped += 1
                continue
            latest = customer.owner_history.filter(revoked_at__isnull=True).order_by("-seq").first()
            if not latest:
                skipped += 1
                continue
            latest.revoked_at = now
            latest.save(update_fields=["revoked_at"])
            if latest.from_user:
                customer.owner = latest.from_user
                customer.status = CustomerStatus.FOLLOWING
                customer.pool_type = None
            else:
                customer.owner = None
                customer.status = CustomerStatus.POOL
                customer.pool_type = PoolType.SQUARE if latest.source_type == OwnerHistorySourceType.SQUARE else PoolType.AUTO
            customer.updated_at = now
            customer.save()
            cnt += 1
        msg = f"已撤销 {cnt} 个客户的分配，回退到上一持有人"
        if skipped:
            msg += f"；{skipped} 个已成交或无历史记录，已跳过"
        self.message_user(request, msg, messages.SUCCESS if cnt else messages.WARNING)


@admin.register(Receipt)
class ReceiptAdmin(RolePermissionsMixin, admin.ModelAdmin):
    """收款记录——财务/总经办可查,咨询师填写(细则:收款留痕不复核)."""
    list_display = ("customer", "amount", "received_at", "recorded_by", "created_at")
    list_filter = ("received_at",)
    search_fields = ("customer__company", "note")
    readonly_fields = ("customer", "recorded_by", "created_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("customer", "recorded_by")
        if getattr(request.user, "role", None) == Role.TECH:
            return qs.none()  # 技术部不可见财务
        return qs


@admin.register(Cost)
class CostAdmin(RolePermissionsMixin, admin.ModelAdmin):
    """支出/成本记录——咨询师申请,总经办审核通过才计入成本(细则)."""
    list_display = ("customer", "amount", "category", "status", "recorded_by", "created_at")
    list_filter = ("status", "category")
    search_fields = ("customer__company", "note")
    readonly_fields = ("customer", "recorded_by", "created_at")
    actions = ["approve_costs", "reject_costs"]

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("customer", "recorded_by", "reviewed_by")
        if getattr(request.user, "role", None) == Role.TECH:
            return qs.none()  # 技术部不可见财务
        return qs

    @admin.action(description="审核通过所选支出(计入成本)")
    def approve_costs(self, request, queryset):
        n = queryset.filter(status=CostStatus.PENDING).update(
            status=CostStatus.APPROVED, reviewed_by=request.user, reviewed_at=timezone.now()
        )
        self.message_user(request, f"已通过 {n} 条支出")

    @admin.action(description="驳回所选支出")
    def reject_costs(self, request, queryset):
        n = queryset.filter(status=CostStatus.PENDING).update(
            status=CostStatus.REJECTED, reviewed_by=request.user, reviewed_at=timezone.now()
        )
        self.message_user(request, f"已驳回 {n} 条支出")


@admin.register(VisitLog)
class VisitLogAdmin(RolePermissionsMixin, admin.ModelAdmin):
    """用户行为——谁/何时/访问了什么路径/状态码(302=被踢回登录页事件),行为后台可查."""

    list_display = ("created_at", "user", "path", "status")
    list_filter = ("user", "status")
    search_fields = ("path",)
    readonly_fields = ("created_at", "user", "path", "status", "session_key")
    date_hierarchy = "created_at"


@admin.register(OperationLog)
class OperationLogAdmin(RolePermissionsMixin, admin.ModelAdmin):
    """提交日志——审计:谁在何时提交/修改了什么信息(客户建档/修改等)."""
    list_display = ("created_at", "user", "action", "target", "detail_short")
    list_filter = ("action", "user")
    search_fields = ("target", "detail")
    readonly_fields = ("created_at", "user", "action", "target", "detail")
    date_hierarchy = "created_at"

    VIEW_ROLES = {Role.ADMIN, Role.SALES_LEAD, Role.CONSULTANT_LEAD}
    CHANGE_ROLES = set()  # 日志只读,不可改
    ADD_ROLES = set()
    DELETE_ROLES = {Role.ADMIN}

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser or getattr(user, "role", None) == Role.ADMIN:
            return qs
        if user.is_authenticated:
            return qs.filter(user=user)  # 普通角色只看自己的操作日志
        return qs.none()

    @admin.display(description="提交信息")
    def detail_short(self, obj: OperationLog) -> str:
        return (obj.detail[:50] + "…") if len(obj.detail) > 50 else obj.detail


@admin.register(RecycledCustomer)
class RecycledCustomerAdmin(RolePermissionsMixin, admin.ModelAdmin):
    """回收站（细则第一页·七）:按角色分权——销售看自己删的/主管看组员+自己/总经办看全部."""
    list_display = ("company_deleted_badge", "contact_name", "phone", "owner", "created_by", "deleted_by", "deleted_at", "history_link")
    search_fields = ("company", "contact_name", "phone")
    list_filter = ("deleted_at",)
    actions = ["restore", "purge"]

    VIEW_ROLES = {Role.SALES, Role.SALES_LEAD, Role.ADMIN}
    CHANGE_ROLES = {Role.ADMIN}
    DELETE_ROLES = {Role.ADMIN}

    def get_queryset(self, request):
        qs = RecycledCustomer.objects.filter(deleted_at__isnull=False)
        user = request.user
        role = getattr(user, "role", None)
        if role == Role.SALES:
            # 销售看自己删的(方案B:误删可自查)
            return qs.filter(deleted_by=user)
        if role == Role.SALES_LEAD:
            # 主管看组员+自己删的
            team = getattr(user, "team", None)
            if team:
                return qs.filter(Q(deleted_by__team=team) | Q(deleted_by=user))
            return qs.filter(deleted_by=user)
        return qs  # 总经办看全部

    def has_add_permission(self, request):
        return False

    def get_fields(self, request, obj=None):
        return [f.name for f in obj._meta.fields if f.name != "id"]

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return []
        return [f.name for f in obj._meta.fields if f.name != "id"]

    @admin.display(description="公司名称（已删除）")
    def company_deleted_badge(self, obj: RecycledCustomer) -> str:
        return format_html(
            '{} <span style="background:#FDE8E8;color:#C0392B;border-radius:4px;padding:1px 6px;font-size:11px">已删除</span>',
            obj.company,
        )
    company_deleted_badge.admin_order_field = "company"  # type: ignore[attr-defined]

    @admin.display(description="修改记录")
    def history_link(self, obj: RecycledCustomer):
        return format_html('<a href="/admin/customers/customer/{}/history/">查看全部修改记录</a>', obj.pk)

    @admin.action(description="恢复到我的客户")
    def restore(self, request, queryset):
        updated = queryset.update(deleted_at=None, updated_at=timezone.now())
        # 留痕:恢复操作记录日志
        try:
            OperationLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="恢复",
                target="客户（回收站）",
                detail="、".join(str(c.company) for c in queryset[:10]) or "(无)",
            )
        except Exception:
            pass
        self.message_user(request, f"已恢复 {updated} 个客户到客户列表", messages.SUCCESS)

    @admin.action(description="彻底删除（不可恢复，仅总经办）")
    def purge(self, request, queryset):
        # 非管理角色禁彻底删除——销售/主管只能软删进回收站,彻底删除仅总经办
        role = getattr(request.user, "role", None)
        if role != Role.ADMIN:
            self.message_user(request, "无权限彻底删除（仅总经办可操作）", messages.ERROR)
            return
        count, _ = queryset.delete()
        # 留痕:彻底删除记录操作日志
        try:
            OperationLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="彻底删除",
                target="客户（回收站）",
                detail="、".join(str(c.company) for c in queryset[:10]) or "(无)",
            )
        except Exception:
            pass
        self.message_user(request, f"已彻底删除 {count} 个客户（含跟进/归属/附图数据）", messages.WARNING)


@admin.register(FollowUp)
class FollowUpAdmin(RolePermissionsMixin, admin.ModelAdmin):
    list_display = ("customer", "user", "content_preview", "created_at")
    search_fields = ("customer__company", "content")

    VIEW_ROLES = FIRST_PAGE_ROLES
    CHANGE_ROLES = set()
    ADD_ROLES = set()
    DELETE_ROLES = FIRST_PAGE_ROLES

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        role = getattr(request.user, "role", None)
        if role == Role.SALES:
            return qs.filter(customer__owner=request.user)
        if role == Role.SALES_LEAD:
            team = getattr(request.user, "team", None)
            if team:
                return qs.filter(Q(customer__owner__team=team) | Q(customer__owner=request.user))
        return qs

    def content_preview(self, obj: FollowUp) -> str:
        return obj.content[:50]
    content_preview.short_description = "内容预览"  # type: ignore[attr-defined]
