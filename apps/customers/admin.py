"""金石管理系统 · 客户管理后台——M1 核心."""
from django.contrib import admin
from django.contrib import messages
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html

from .models import Customer, CustomerStatus, FollowUp, Source


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


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("summary", "phone_masked", "owner", "last_follow_at")
    list_filter = (StatusFilter, SourceFilter, QualificationFilter)
    search_fields = ("company", "contact_name", "phone")
    readonly_fields = ("created_at", "updated_at", "pool_entered_at", "created_by")
    inlines = [FollowUpInline]

    fieldsets = (
        (None, {"fields": ("company", "contact_name", "phone", ("qualification_interest", "source"), "consulted_at", "note")}),
        ("状态与归属", {"fields": ("status", "owner", "pool_entered_at", "last_follow_at", "lost_reason")}),
    )

    actions = ["mark_deal", "move_to_pool", "mark_lost", "claim_from_pool", "assign_pool"]

    # ---------- 按角色过滤可用 Actions——管理层不显示"领取公海"，销售不显示"调配公海" ----------
    def get_actions(self, request):
        actions = super().get_actions(request)
        role = getattr(request.user, "role", None)
        if role == "admin":
            actions.pop("claim_from_pool", None)   # 老板不跟销售抢单
        if role == "sales":
            actions.pop("assign_pool", None)       # 销售不能调配公海客户
        return actions

    # ---------- 行级权限：销售只看自己的客户 ----------
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        role = getattr(request.user, "role", None)
        if role == "sales":
            return qs.filter(owner=request.user)
        if role == "consultant" or role == "tech":
            return qs.none()  # 咨询/技术无客户查看权限
        if role == "finance":
            return qs.filter(status=CustomerStatus.DEAL)
        return qs  # admin/管理层看全部

    def get_changelist_instance(self, request):
        """把 request 暂存到 self，供 list_display 方法（phone_masked）读取角色."""
        cl = super().get_changelist_instance(request)
        self._current_request = request
        return cl

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    # ---------- 汇总列：公司名纯文字，资质+状态用清淡气泡 ----------
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

    # ---------- ��示层脱敏：公海电话仅对销售打码，管理层必须看全号才能调配 ----------
    # ---------- 彩标三列：公司/业务/状态一眼看完 ----------
    STATUS_COLORS = {
        "lead":     ("#9CA3AF", "#F3F4F6", "线索"),
        "following":("#22C55E", "#F0FDF4", "跟进中"),
        "pool":     ("#3B82F6", "#EFF6FF", "公海"),
        "deal":     ("#F59E0B", "#FFFBEB", "已成交"),
        "lost":     ("#EF4444", "#FEF2F2", "已流失"),
    }

    def status_badge(self, obj: Customer) -> str:
        stroke, bg, label = self.STATUS_COLORS.get(obj.status, ("#6B7280", "#F9FAFB", obj.status))
        return format_html(
            '<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
            'background:{};color:{};font-weight:500;font-size:12px">{}</span>',
            bg, stroke, label,
        )
    status_badge.short_description = ""  # type: ignore[attr-defined]
    status_badge.admin_order_field = "status"  # type: ignore[attr-defined]

    def qualification_tag(self, obj: Customer) -> str:
        q = obj.qualification_interest or "未填"
        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:8px;'
            'background:#EEF2FF;color:#4338CA;font-size:11px;font-weight:500">{}</span>',
            q.replace("（组合套餐）", ""),
        )
    qualification_tag.short_description = "资质"  # type: ignore[attr-defined]

    def source_badge(self, obj: Customer) -> str:
        s = obj.get_source_display()
        colors = {"转介绍": ("#F97316", "#FFF7ED"), "主动咨询": ("#8B5CF6", "#F5F3FF"),
                  "广告投放": ("#EC4899", "#FDF2F8")}
        stroke, bg = colors.get(s, ("#6B7280", "#F9FAFB"))
        return format_html(
            '<span style="padding:1px 8px;border-radius:8px;background:{};color:{};font-size:11px">{}</span>',
            bg, stroke, s,
        )
    source_badge.short_description = "来源"  # type: ignore[attr-defined]
    def phone_masked(self, obj: Customer) -> str:
        phone = obj.phone
        if obj.status == CustomerStatus.POOL and len(phone) >= 7:
            request = getattr(self, "_current_request", None)
            viewer_role = getattr(getattr(request, "user", None), "role", None)
            if viewer_role != "admin":  # 销售/咨询/技术/财务都脱敏；只有 admin(管理层) 看全号
                return f"{phone[:3]}****{phone[-4:]}"
        return phone
    phone_masked.short_description = "电话"  # type: ignore[attr-defined]

    # ---------- Admin Actions（状态机动作） ----------
    @admin.action(description="✅ 成交（一键立项占位）")
    def mark_deal(self, request, queryset):
        updated = queryset.filter(status__in=[CustomerStatus.LEAD, CustomerStatus.FOLLOWING]).update(
            status=CustomerStatus.DEAL, updated_at=timezone.now()
        )
        msg = f"{updated} 个客户已标记为成交。立项功能将在 M2 实现。"
        self.message_user(request, msg, messages.SUCCESS)

    @admin.action(description="🌊 掉入公海")
    def move_to_pool(self, request, queryset):
        now = timezone.now()
        # 销售不可主动把别人的客户推公海
        if getattr(request.user, "role", None) == "sales":
            queryset = queryset.filter(owner=request.user)
        updated = queryset.filter(status=CustomerStatus.FOLLOWING).update(
            status=CustomerStatus.POOL, owner=None, pool_entered_at=now, updated_at=now
        )
        cnt = updated if isinstance(updated, int) else 0
        self.message_user(request, f"{cnt} 个客户已掉入公海", messages.SUCCESS)

    @admin.action(description="❌ 标记流失")
    def mark_lost(self, request, queryset):
        if getattr(request.user, "role", None) == "sales":
            queryset = queryset.filter(owner=request.user)
        updated = queryset.filter(status__in=[CustomerStatus.FOLLOWING, CustomerStatus.POOL]).update(
            status=CustomerStatus.LOST, updated_at=timezone.now()
        )
        cnt = updated if isinstance(updated, int) else 0
        self.message_user(request, f"{cnt} 个客户已标记流失", messages.SUCCESS)

    @admin.action(description="📥 领取公海客户")
    def claim_from_pool(self, request, queryset):
        if getattr(request.user, "role", None) != "sales":
            self.message_user(request, "仅销售可领取公海客户", messages.ERROR)
            return
        now = timezone.now()
        updated = queryset.filter(status=CustomerStatus.POOL).update(
            status=CustomerStatus.FOLLOWING,
            owner=request.user,
            pool_entered_at=None,
            last_follow_at=now,
            updated_at=now,
        )
        cnt = updated if isinstance(updated, int) else 0
        self.message_user(request, f"已领取 {cnt} 个公海客户", messages.SUCCESS)

    @admin.action(description="👑 调配公海客户（指定销售+理由弹窗）")
    def assign_pool(self, request, queryset):
        """中间页选择目标销售 + 理由后执行调配."""
        if "apply" in request.POST:
            new_owner_id = request.POST.get("new_owner")
            reason = request.POST.get("reason", "").strip()
            if not new_owner_id:
                self.message_user(request, "请选择目标销售", messages.ERROR)
                return None
            if not reason:
                self.message_user(request, "请填写调配理由", messages.ERROR)
                return None
            from apps.accounts.models import User
            new_owner = User.objects.get(id=new_owner_id)
            now = timezone.now()
            updated = queryset.filter(status=CustomerStatus.POOL).update(
                status=CustomerStatus.FOLLOWING, owner=new_owner, pool_entered_at=None,
                last_follow_at=now, updated_at=now,
            )
            cnt = updated if isinstance(updated, int) else 0
            self.message_user(request, f"已将 {cnt} 个公海客户调配给 {new_owner.real_name}（理由: {reason}）", messages.SUCCESS)
            return None
        # 中间页
        from apps.accounts.models import Role, User
        sales_users = User.objects.filter(role=Role.SALES, is_active=True)
        context = dict(
            self.admin_site.each_context(request),
            title="调配公海客户",
            action_checkbox_name=admin.helpers.ACTION_CHECKBOX_NAME,
            queryset=queryset.filter(status=CustomerStatus.POOL),
            sales_users=sales_users,
        )
        return TemplateResponse(request, "admin/customers/assign_pool.html", context)


@admin.register(FollowUp)
class FollowUpAdmin(admin.ModelAdmin):
    list_display = ("customer", "user", "content_preview", "created_at")
    search_fields = ("customer__company", "content")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        role = getattr(request.user, "role", None)
        if role == "sales":
            return qs.filter(customer__owner=request.user)
        return qs

    def content_preview(self, obj: FollowUp) -> str:
        return obj.content[:50]
    content_preview.short_description = "内容预览"  # type: ignore[attr-defined]
