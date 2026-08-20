"""金石管理系统 · 客户管理后台——M1 核心 + v2 客户池广场/撤销栈 + 回收站 + 撞单预检.

对照《金石企服客户管理系统搭建细则》第一页:
- 三、权限:销售看自己/主管看组员+自己/总经办看全部
- 四、分配:主管/总经办可分配管辖内客户（不限公海）并撤回
- 五、客户池广场:释放后全员可见,获取后归属到获取人,来源栏署名"客户池广场-XX"
- 六、撞单:录入前 JS 预检弹窗 + 录入后标识 + 送总经办信息箱
- 七、回收站:删除进回收站（软删）,总经办可查看已删客户及全部修改记录
"""
import threading

from django.contrib import admin, messages
from django.db.models import Q
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html

from apps.accounts.admin_mixins import FIRST_PAGE_ROLES, RolePermissionsMixin
from apps.accounts.models import Notification, Role, User
from simple_history.admin import SimpleHistoryAdmin

from .models import (
    Customer,
    CustomerAttachment,
    CustomerOwnerHistory,
    CustomerStatus,
    FollowUp,
    OperationLog,
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
        return [(None, "全部")] + [(s.value, s.label) for s in Source]
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


# 各角色可用动作白名单——get_actions 按此过滤,默认 delete_selected(硬删)一并不再暴露
_ROLE_ACTIONS = {
    Role.SALES: {"mark_deal", "move_to_pool", "mark_lost", "claim_from_pool", "release_to_square", "soft_delete"},
    Role.SALES_LEAD: {"mark_deal", "move_to_pool", "mark_lost", "claim_from_pool", "release_to_square",
                      "soft_delete", "assign_pool", "revoke_assignment"},
    Role.ADMIN: {"mark_deal", "move_to_pool", "mark_lost", "release_to_square",
                 "soft_delete", "assign_pool", "revoke_assignment"},
}


@admin.register(Customer)
class CustomerAdmin(RolePermissionsMixin, SimpleHistoryAdmin):
    list_display = ("summary", "phone_masked", "owner", "follow_staff_display", "quote_amount", "last_follow_at")
    empty_value_display = "—"
    list_filter = (OwnerFilter, StatusFilter, SourceFilter, QualificationFilter)
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

    def formfield_for_dbfield(self, db_field, **kwargs):
        if db_field.name == "qualification_interest":
            # JSONField 的 formfield 会传 encoder 参数给 MultipleChoiceField 导致 TypeError,
            # 因此不走 super() 路径,直接构造多选复选框字段
            from django import forms
            field = forms.MultipleChoiceField(
                choices=self.QUALIFICATION_CHOICES,
                widget=forms.CheckboxSelectMultiple,
                required=False,
                label=db_field.verbose_name,
                help_text=db_field.help_text,
            )
            return field
        return super().formfield_for_dbfield(db_field, **kwargs)
    readonly_fields = (
        "source_signature", "created_at", "updated_at", "pool_entered_at", "created_by", "square_released_by",
        "duplicate_flagged_at",
    )
    inlines = [FollowUpInline, OwnerHistoryInline, CustomerAttachmentInline]

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
                ("source", "quote_amount"),
                "consulted_at", "note",
            ),
        }),
    )

    actions = [
        "mark_deal", "move_to_pool", "mark_lost",
        "claim_from_pool", "assign_pool",
        "release_to_square", "revoke_assignment", "soft_delete",
    ]

    class Media:
        css = {"all": ("admin/css/change_form_inline_fix.css",)}

    VIEW_ROLES = FIRST_PAGE_ROLES
    ADD_ROLES = FIRST_PAGE_ROLES
    CHANGE_ROLES = FIRST_PAGE_ROLES
    DELETE_ROLES = FIRST_PAGE_ROLES

    # ---------- 表单结构 ----------

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        # 编辑态:所有角色只显示基本信息——状态/归属/公海等系统字段由列表列与归属历史展示,
        # 流转必须走分配/释放/领取等 action,不在表单裸露
        return (
            ("基本信息", {
                "fields": (
                    ("company", "contact_name"),
                    ("phone", "qualification_interest"),
                    ("source", "quote_amount"),
                    "consulted_at", "note",
                ),
            }),
        )

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            # 编辑态:归属与状态字段一律只读,防止绕过署名/历史旁路
            base += ["owner", "status", "pool_type", "last_follow_at", "lost_reason"]
        return base

    def get_actions(self, request):
        actions = super().get_actions(request)
        allowed = _ROLE_ACTIONS.get(getattr(request.user, "role", None), set())
        return {name: fn for name, fn in actions.items() if name in allowed}

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        role = getattr(user, "role", None)
        if role == Role.SALES:
            # 销售看自己客户 + 公海客户(细则五'客户池广场所有人员可见')
            return qs.filter(Q(owner=user) | Q(status=CustomerStatus.POOL))
        if role == Role.SALES_LEAD:
            # 主管看组员+自己（细则第一页·三）,不依赖主管本人是否填在 team 里
            team = getattr(user, "team", None)
            if team:
                return qs.filter(Q(owner__team=team) | Q(owner=user))
            return qs.filter(owner=user)
        if role == Role.ADMIN:
            return qs
        # 咨询/技术/财务不看第一页客户（v2 细则第一页仅销售序列与总经办）
        return qs.none()

    def get_changelist_instance(self, request):
        cl = super().get_changelist_instance(request)
        _request_local.request = request
        return cl

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
            for admin_user in admins:
                Notification.objects.create(
                    recipient=admin_user,
                    title="撞单提醒",
                    content=f"客户「{obj.company}」与「{dup_names}」疑似重复（录入人:{request.user.real_name}），请核查归属。",
                    link="/admin/customers/customer/",
                )

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
        obj.save(update_fields=["deleted_at", "updated_at"])

    def delete_queryset(self, request, queryset):
        # 批量删除兜底走软删
        queryset.update(deleted_at=timezone.now(), updated_at=timezone.now())

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

    # ---------- 撞单预检（录入前弹窗的数据接口） ----------

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "check-duplicates/",
                self.admin_site.admin_view(self.check_duplicates_view),
                name="customers_customer_check_duplicates",
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
        for field, value in (
            ("company", request.GET.get("company", "")),
            ("contact_name", request.GET.get("contact", "")),
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

    @admin.action(description="成交（自动创建项目）")
    def mark_deal(self, request, queryset):
        """成交时：客户状态改 DEAL + 自动创建 Project 并做字段快照（幂等,不会重复建项目）."""
        from apps.projects.models import Project
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "仅销售序列/总经办可操作成交", messages.ERROR)
            return
        candidates = list(queryset.filter(status__in=[CustomerStatus.LEAD, CustomerStatus.FOLLOWING]))
        cnt = 0
        for customer in candidates:
            customer.status = CustomerStatus.DEAL
            customer.updated_at = timezone.now()
            customer.save(update_fields=["status", "updated_at"])
            Project.objects.get_or_create(
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
            cnt += 1
        self.message_user(request, f"{cnt} 个客户已成交，已自动创建对应项目，等待嘉茵分配咨询师。", messages.SUCCESS)

    @admin.action(description="释放客户到公海")
    def move_to_pool(self, request, queryset):
        role = getattr(request.user, "role", None)
        if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
            self.message_user(request, "无权限执行该操作", messages.ERROR)
            return
        if role == Role.SALES:
            queryset = queryset.filter(owner=request.user)
        # 线索(LEAD)/跟进中(FOLLOWING)均可释放进公海——原只认FOLLOWING导致LEAD客户'0个生效'
        updated = queryset.filter(status__in=[CustomerStatus.LEAD, CustomerStatus.FOLLOWING]).update(
            status=CustomerStatus.POOL, pool_type=PoolType.AUTO, owner=None,
            pool_entered_at=timezone.now(), updated_at=timezone.now(),
        )
        self.message_user(request, f"{updated} 个客户已释放到公海", messages.SUCCESS)

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
        self.message_user(request, f"{updated} 个客户已标记流失", messages.SUCCESS)

    @admin.action(description="删除（进入回收站）")
    def soft_delete(self, request, queryset):
        updated = queryset.update(deleted_at=timezone.now(), updated_at=timezone.now())
        self.message_user(
            request, f"{updated} 个客户已移入回收站（总经办可查看/恢复）", messages.SUCCESS,
        )

    @admin.action(description="领取公海客户")
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
            Notification.objects.create(
                recipient=new_owner,
                title="客户分配通知",
                content=f"{request.user.real_name} 将 {cnt} 个客户分配给你（理由:{reason}），请及时跟进。",
                link="/admin/customers/customer/",
            )
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

    @admin.action(description="释放到客户池广场")
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
            self.message_user(request, f"已释放 {cnt} 个客户到客户池广场（理由: {reason}）", messages.SUCCESS)
            return None
        candidates = queryset.filter(status__in=[CustomerStatus.LEAD, CustomerStatus.FOLLOWING])
        context = dict(
            self.admin_site.each_context(request),
            title="释放到客户池广场",
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
    """回收站（细则第一页·七）:总经办查看已删除客户 + 全部修改记录 + 恢复/彻底删除."""
    list_display = ("company_deleted_badge", "contact_name", "phone", "owner", "created_by", "deleted_at", "history_link")
    search_fields = ("company", "contact_name", "phone")
    list_filter = ("deleted_at",)
    actions = ["restore", "purge"]

    VIEW_ROLES = {Role.ADMIN}
    CHANGE_ROLES = {Role.ADMIN}
    DELETE_ROLES = {Role.ADMIN}

    def get_queryset(self, request):
        return RecycledCustomer.objects.filter(deleted_at__isnull=False)

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

    @admin.action(description="恢复到客户列表")
    def restore(self, request, queryset):
        updated = queryset.update(deleted_at=None, updated_at=timezone.now())
        self.message_user(request, f"已恢复 {updated} 个客户到客户列表", messages.SUCCESS)

    @admin.action(description="彻底删除（不可恢复）")
    def purge(self, request, queryset):
        count, _ = queryset.delete()
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
