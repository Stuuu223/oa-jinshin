"""金石管理系统 · 客户管理后台——M1 核心 + v2 客户池广场/撤销栈."""
from django.contrib import admin
from django.contrib import messages
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.html import format_html

from apps.accounts.models import LEAD_ROLES, Role

from .models import (
    Customer,
    CustomerOwnerHistory,
    CustomerStatus,
    FollowUp,
    OwnerHistorySourceType,
    PoolType,
    Source,
)


# ── 过滤器：加默认"全部"选项，展开后一目了然 ──
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


class FollowUpInline(admin.TabularInline):
    model = FollowUp
    extra = 0
    fields = ("content", "created_at")
    readonly_fields = ("created_at",)
    can_delete = True
    verbose_name_plural = "跟进记录"

    def formfield_for_dbfield(self, db_field, **kwargs):
        if db_field.name == "content":
            kwargs["widget"] = admin.widgets.AdminTextInputWidget()
        return super().formfield_for_dbfield(db_field, **kwargs)


class OwnerHistoryInline(admin.TabularInline):
    """归属变更历史——只读时间线，v2 claim 新增."""
    model = CustomerOwnerHistory
    extra = 0
    fields = ("seq", "from_user", "to_user", "source_type", "source_note", "operator", "assigned_at", "revoked_at")
    readonly_fields = fields
    can_delete = False
    verbose_name_plural = "归属变更历史（署名/撤销依据）"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("summary", "phone_masked", "owner", "quote_amount", "last_follow_at")
    list_filter = (StatusFilter, SourceFilter, QualificationFilter)
    search_fields = ("company", "contact_name", "phone")
    readonly_fields = ("created_at", "updated_at", "pool_entered_at", "created_by", "square_released_by")
    inlines = [FollowUpInline, OwnerHistoryInline]

    fieldsets = (
        (None, {"fields": ("company", "contact_name", "phone", ("qualification_interest", "source"), "quote_amount", "consulted_at", "note")}),
        ("状态与归属", {"fields": ("status", "pool_type", "owner", "square_released_by", "pool_entered_at", "last_follow_at", "lost_reason")}),
    )

    actions = [
        "mark_deal", "move_to_pool", "mark_lost",
        "claim_from_pool", "assign_pool",
        "release_to_square", "revoke_assignment",
    ]

    # ---------- 按角色过滤可用 Actions ----------
    def get_actions(self, request):
        actions = super().get_actions(request)
        role = getattr(request.user, "role", None)
        if role == Role.ADMIN:
            actions.pop("claim_from_pool", None)   # 总经办不跟销售抢单
        if role == Role.SALES:
            actions.pop("assign_pool", None)       # 普通销售不能调配公海客户
        if role not in LEAD_ROLES and role != Role.ADMIN:
            actions.pop("assign_pool", None)       # 只有主管/总经办能调配
        return actions

    # ---------- 行级权限：销售看自己；销售主管看组员+自己；总经办看全部 ----------
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        role = getattr(user, "role", None)
        if role == Role.SALES:
            return qs.filter(owner=user)
        if role == Role.SALES_LEAD:
            team = getattr(user, "team", None)
            if team:
                return qs.filter(models_q_owner_in_team(team))
            return qs.filter(owner=user)
        if role in (Role.CONSULTANT, Role.TECH):
            return qs.none()  # 客户信息管理页对咨询/技术不开放（成交后转入第二页另有权限）
        if role == Role.FINANCE:
            return qs.filter(status=CustomerStatus.DEAL)
        return qs  # admin/总经办看全部

    def get_changelist_instance(self, request):
        cl = super().get_changelist_instance(request)
        self._current_request = request
        return cl

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            CustomerOwnerHistory.objects.create(
                customer=obj, from_user=None, to_user=obj.owner or request.user,
                source_type=OwnerHistorySourceType.DIRECT_INPUT,
                operator=request.user, seq=1,
            )
        super().save_model(request, obj, form, change)

    def summary(self, obj: Customer) -> str:
        qual = (obj.qualification_interest or "未填").replace("（组合套餐）", "")
        status_label = obj.get_status_display()
        return format_html(
            "{}  <span style='padding:1px 7px;border-radius:6px;background:#E8EDFB;"
            "color:#3B5098;font-size:11px'>{}</span>  "
            "<span style='padding:1px 8px;border-radius:6px;background:#E8F5E9;"
            "color:#2E7D32;font-size:11px'>{}</span>",
            obj.company, qual, status_label,
        )
    summary.short_description = "公司 / 业务 / 进度"  # type: ignore[attr-defined]
    summary.admin_order_field = "company"  # type: ignore[attr-defined]

    def phone_masked(self, obj: Customer) -> str:
        phone = obj.phone
        if obj.status == CustomerStatus.POOL and len(phone) >= 7:
            request = getattr(self, "_current_request", None)
            viewer_role = getattr(getattr(request, "user", None), "role", None)
            if viewer_role != Role.ADMIN:
                return f"{phone[:3]}****{phone[-4:]}"
        return phone
    phone_masked.short_description = "电话"  # type: ignore[attr-defined]

    # ---------- Admin Actions（状态机动作） ----------
    @admin.action(description="✅ 成交（一键立项占位）")
    def mark_deal(self, request, queryset):
        updated = queryset.filter(status__in=[CustomerStatus.LEAD, CustomerStatus.FOLLOWING]).update(
            status=CustomerStatus.DEAL, updated_at=timezone.now()
        )
        self.message_user(request, f"{updated} 个客户已标记为成交。立项功能将在 M2 实现。", messages.SUCCESS)

    @admin.action(description="🌊 掉入公海（自动/手动）")
    def move_to_pool(self, request, queryset):
        now = timezone.now()
        if getattr(request.user, "role", None) == Role.SALES:
            queryset = queryset.filter(owner=request.user)
        updated = queryset.filter(status=CustomerStatus.FOLLOWING).update(
            status=CustomerStatus.POOL, pool_type=PoolType.AUTO, owner=None,
            pool_entered_at=now, updated_at=now,
        )
        cnt = updated if isinstance(updated, int) else 0
        self.message_user(request, f"{cnt} 个客户已掉入公海", messages.SUCCESS)

    @admin.action(description="❌ 标记流失")
    def mark_lost(self, request, queryset):
        if getattr(request.user, "role", None) == Role.SALES:
            queryset = queryset.filter(owner=request.user)
        updated = queryset.filter(status__in=[CustomerStatus.FOLLOWING, CustomerStatus.POOL]).update(
            status=CustomerStatus.LOST, updated_at=timezone.now()
        )
        cnt = updated if isinstance(updated, int) else 0
        self.message_user(request, f"{cnt} 个客户已标记流失", messages.SUCCESS)

    @admin.action(description="📥 领取公海客户")
    def claim_from_pool(self, request, queryset):
        if getattr(request.user, "role", None) not in (Role.SALES, Role.SALES_LEAD):
            self.message_user(request, "仅销售/销售主管可领取公海客户", messages.ERROR)
            return
        now = timezone.now()
        for customer in queryset.filter(status=CustomerStatus.POOL):
            last = customer.owner_history.order_by("-seq").first()
            next_seq = (last.seq + 1) if last else 1
            square_source_note = customer.source if customer.pool_type == PoolType.SQUARE else ""
            customer.status = CustomerStatus.FOLLOWING
            customer.owner = request.user
            customer.pool_entered_at = None
            customer.pool_type = None
            customer.last_follow_at = now
            customer.updated_at = now
            customer.save()
            CustomerOwnerHistory.objects.create(
                customer=customer, from_user=None, to_user=request.user,
                source_type=(OwnerHistorySourceType.SQUARE if square_source_note else OwnerHistorySourceType.SALES_CLAIM),
                operator=request.user, seq=next_seq,
            )
        self.message_user(request, f"已领取 {queryset.count()} 个公海客户", messages.SUCCESS)

    @admin.action(description="👑 调配公海客户（指定销售+理由弹窗）")
    def assign_pool(self, request, queryset):
        """中间页选择目标销售 + 理由后执行调配（销售主管/总经办可用）."""
        if "apply" in request.POST:
            new_owner_id = request.POST.get("new_owner")
            reason = request.POST.get("reason", "").strip()
            if not new_owner_id or not reason:
                self.message_user(request, "请选择目标销售并填写调配理由", messages.ERROR)
                return None
            from apps.accounts.models import User
            new_owner = User.objects.get(id=new_owner_id)
            now = timezone.now()
            role = getattr(request.user, "role", None)
            source_type = OwnerHistorySourceType.BOSS_ASSIGN if role == Role.ADMIN else OwnerHistorySourceType.MANAGER_ASSIGN
            cnt = 0
            for customer in queryset.filter(status=CustomerStatus.POOL):
                last = customer.owner_history.order_by("-seq").first()
                next_seq = (last.seq + 1) if last else 1
                customer.status = CustomerStatus.FOLLOWING
                customer.owner = new_owner
                customer.pool_entered_at = None
                customer.pool_type = None
                customer.last_follow_at = now
                customer.updated_at = now
                customer.save()
                CustomerOwnerHistory.objects.create(
                    customer=customer, from_user=None, to_user=new_owner,
                    source_type=source_type, source_note=reason,
                    operator=request.user, seq=next_seq,
                )
                cnt += 1
            self.message_user(request, f"已将 {cnt} 个公海客户调配给 {new_owner.real_name}（理由: {reason}）", messages.SUCCESS)
            return None
        from apps.accounts.models import Role as RoleEnum, User
        sales_users = User.objects.filter(role__in=[RoleEnum.SALES, RoleEnum.SALES_LEAD], is_active=True)
        context = dict(
            self.admin_site.each_context(request),
            title="调配公海客户",
            action_checkbox_name=admin.helpers.ACTION_CHECKBOX_NAME,
            queryset=queryset.filter(status=CustomerStatus.POOL),
            sales_users=sales_users,
        )
        return TemplateResponse(request, "admin/customers/assign_pool.html", context)

    @admin.action(description="🏟️ 释放到客户池广场")
    def release_to_square(self, request, queryset):
        """v2 claim 新增：销售/销售主管/总经办可主动释放自己管辖的客户到广场.

        与'掉入公海'共用 status=pool，靠 pool_type=SQUARE 区分，
        来源栏自动署名'客户池广场-XX（释放人）'。
        """
        role = getattr(request.user, "role", None)
        if role == Role.SALES:
            queryset = queryset.filter(owner=request.user)
        now = timezone.now()
        cnt = 0
        for customer in queryset.filter(status=CustomerStatus.FOLLOWING):
            releaser_name = request.user.real_name
            customer.status = CustomerStatus.POOL
            customer.pool_type = PoolType.SQUARE
            customer.square_released_by = request.user
            customer.source = f"客户池广场-{releaser_name}"
            customer.owner = None
            customer.pool_entered_at = now
            customer.updated_at = now
            customer.save()
            cnt += 1
        self.message_user(request, f"已释放 {cnt} 个客户到客户池广场", messages.SUCCESS)

    @admin.action(description="↩️ 撤销分配（回退到上一持有人）")
    def revoke_assignment(self, request, queryset):
        """v2 claim 新增：栈式撤销——弹出最新一条未撤销历史记录，恢复上一状态.

        边界规则：已成交（status=deal）客户不可撤销分配。
        详见 14-老板最新Claim与变更执行清单-v2.md §三 决策 2。
        """
        role = getattr(request.user, "role", None)
        if role not in (list(LEAD_ROLES) + [Role.ADMIN]):
            self.message_user(request, "仅销售主管/咨询主管/总经办可撤销分配", messages.ERROR)
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


def models_q_owner_in_team(team):
    """辅助函数：构造'归属人属于该团队'的 Q 查询，供销售主管行级过滤复用."""
    from django.db.models import Q
    return Q(owner__team=team)


@admin.register(FollowUp)
class FollowUpAdmin(admin.ModelAdmin):
    list_display = ("customer", "user", "content_preview", "created_at")
    search_fields = ("customer__company", "content")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        role = getattr(request.user, "role", None)
        if role == Role.SALES:
            return qs.filter(customer__owner=request.user)
        if role == Role.SALES_LEAD:
            team = getattr(request.user, "team", None)
            if team:
                return qs.filter(customer__owner__team=team)
        return qs

    def content_preview(self, obj: FollowUp) -> str:
        return obj.content[:50]
    content_preview.short_description = "内容预览"  # type: ignore[attr-defined]
