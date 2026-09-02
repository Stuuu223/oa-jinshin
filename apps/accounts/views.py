# -*- coding: utf-8 -*-
"""总经办数据总览视图——M5 驾驶舱首页."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Notification, Role, User
from apps.customers.models import Customer, CustomerStatus
from apps.projects.models import Project, ProjectExpense, ProjectPayment


def dashboard(request):
    """总览面板:线索→成交漏斗/回款/利润/各部门待办/撞单提醒.

    权限:仅管理层(总经办 ADMIN)可看老板总览;其他角色按角色重定向到自己的工作台,
    防止销售/咨询/技术越权查看全公司财务与客户数据(细则权限边界).
    """
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect_to_login(request.get_full_path())

    role = getattr(request.user, "role", None)
    if role != Role.ADMIN:
        # 非管理层:按角色回各自工作台(SSOT 映射,与侧边栏一致)
        workbench = {
            Role.SALES: "sales_workbench",
            Role.SALES_LEAD: "sales_workbench",
            Role.CONSULTANT: "consult_workbench",
            Role.CONSULTANT_LEAD: "consult_workbench",
        }.get(role)
        if workbench:
            return redirect(reverse(workbench))
        # 无工作台角色(技术等):回技术数据总览——不能回 /admin/(首页=dashboard 会再次 302,死循环)
        return redirect(reverse("tech_workbench"))

    # ── 客户漏斗 ──
    total_customers = Customer.objects.count()
    funnel = {
        "线索": Customer.objects.filter(status=CustomerStatus.LEAD).count(),
        "跟进中": Customer.objects.filter(status=CustomerStatus.FOLLOWING).count(),
        "公海": Customer.objects.filter(status=CustomerStatus.POOL).count(),
        "已成交": Customer.objects.filter(status=CustomerStatus.DEAL).count(),
        "已流失": Customer.objects.filter(status=CustomerStatus.LOST).count(),
    }
    converted = funnel["已成交"]
    convert_rate = round(converted / total_customers * 100, 1) if total_customers else 0

    # ── 成交客户与财务(一表化:原项目表并入成交客户,财务=客户侧收款/支出) ──
    from apps.customers.models import Cost as _Cost, CostStatus as _CostStatus, Receipt as _Receipt
    deals = Customer.objects.filter(status=CustomerStatus.DEAL)
    total_projects = deals.count()
    site_progress = {
        "待开始": deals.filter(site_progress="not_started").count(),
        "进行中": deals.filter(site_progress="in_progress").count(),
        "已完成": deals.filter(site_progress__in=["completed_pending", "deployed"]).count(),
    }
    income = _Receipt.objects.filter(customer__status=CustomerStatus.DEAL).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    expense = _Cost.objects.filter(customer__status=CustomerStatus.DEAL, status=_CostStatus.APPROVED).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    profit = income - expense

    # ── 部门待办 ──
    today = timezone.localdate()
    due_soon = deals.filter(created_at__date__gte=today).count()
    unread_count = Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()
    dept_todos = {
        "销售:待跟进客户": Customer.objects.filter(status=CustomerStatus.LEAD).count(),
        "咨询:待分配成交客户": deals.filter(consultant__isnull=True).count(),
        "技术:待开始建站": deals.filter(site_progress="not_started").count(),
        "总经办:未读通知": unread_count,
    }

    # ── 撞单提醒(明细:谁和谁撞了哪个单) ──
    dup_customers = Customer.objects.filter(duplicate_flagged_at__isnull=False).order_by("-duplicate_flagged_at")[:10]
    dup_details = []
    for c in dup_customers:
        # 撞单去重+主客:一对撞单只显示一次——只显示'后建档'的撞单方(先建档=已有客户,后建档=撞单新客户)
        # 跳过'先建档'的一方(该对由后建档方显示),消除双向互相撞的重复
        targets = [d for d in c.find_duplicates()[:5]
                   if d.created_at and c.created_at and d.created_at < c.created_at]
        if not targets:
            continue
        dup_pairs = []
        owner_text = ""
        for d in sorted(targets, key=lambda x: x.created_at):  # 先建档排前=归属方(先到先得)
            who = d.created_by.real_name if d.created_by else "未知"
            if not owner_text:
                owner_text = f"{d.company}（{who}·{d.created_at:%m-%d %H:%M}建档）"
            dup_pairs.append({
                "target": f"{d.company}（{who}建档·{d.created_at:%m-%d %H:%M}）",
                "fields": c.match_fields(d),
                "confidence": c.match_confidence(d),
            })
        dup_details.append({
            "id": c.pk,
            "company": c.company,
            "created_by": c.created_by.real_name if c.created_by else "未知",
            "flagged_at": c.duplicate_flagged_at,
            "created_at": c.created_at,
            "owner": owner_text,  # 归属方(先建档,资源归它)
            "dup_pairs": dup_pairs,
        })
    # 横幅条数与明细条数同一数据源(标识客户数),避免"2条却显示4条"
    dup_alerts = len(dup_details)

    context = dict(
        self_service=request,
        title="总经办数据总览",
        total_customers=total_customers,
        funnel=funnel,
        convert_rate=convert_rate,
        total_projects=total_projects,
        site_progress=site_progress,
        income=income,
        expense=expense,
        profit=profit,
        dept_todos=dept_todos,
        unread_count=unread_count,
        dup_alerts=dup_alerts,
        dup_details=dup_details,
    )
    return render(request, "admin/dashboard.html", context)


def notification_unread(request):
    """侧边栏信息箱未读徽标数据接口——返回当前用户未读数 JSON."""
    from django.http import JsonResponse

    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"count": 0})
    count = Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()
    return JsonResponse({"count": count})


def sales_workbench(request):
    """销售数据总览——销售视角聚合:我的客户/待跟进/撞单/快捷操作."""
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect("/admin/login/?next=/admin/sales-workbench/")

    # 角色边界:仅销售/销售主管/总经办可看销售数据总览,其他角色直访 302 回自己工作台
    role = getattr(request.user, "role", None)
    if role not in (Role.SALES, Role.SALES_LEAD, Role.ADMIN):
        if role in (Role.CONSULTANT, Role.CONSULTANT_LEAD):
            return redirect(reverse("consult_workbench"))
        return redirect("/admin/")

    from django.utils import timezone as tz
    from datetime import timedelta

    me = request.user
    role = getattr(me, "role", None)
    # 总经办(admin):看全部客户(老板全景视角)
    if role == "admin":
        my_customers = Customer.objects.all()
    # 销售主管可见组员+自己,销售仅自己
    elif role == "sales_lead" and me.team:
        team_users = [u.pk for u in me.team.members.all()]
        my_customers = Customer.objects.filter(owner_id__in=team_users)
    else:
        my_customers = Customer.objects.filter(owner=me)

    # 按状态分组
    status_groups = {}
    for c in my_customers:
        key = c.get_status_display()
        status_groups.setdefault(key, []).append(c)

    # 待跟进:最近跟进超过 7 天仍未成交
    week_ago = tz.now() - timedelta(days=7)
    stale = my_customers.filter(
        status__in=["lead", "following"],
        last_follow_at__lt=week_ago,
    ).order_by("last_follow_at")[:10]

    # 撞单标识客户(信息维度对齐总览):撞谁/被撞/相同字段/置信度/归属
    dup_customers = my_customers.filter(duplicate_flagged_at__isnull=False)[:10]
    dup = []
    for c in dup_customers:
        # 不去先后过滤:撞单标识客户可能是撞单方(后建档)或被撞方(先建档),都显示全部撞单对
        targets = [d for d in c.find_duplicates()[:5]]
        pairs = []
        owner_text = ""
        for d in sorted(targets, key=lambda x: x.created_at):  # 最早建档=归属方
            who = d.created_by.real_name if d.created_by else "未知"
            if not owner_text:
                owner_text = f"{d.company}（{who}·{d.created_at:%m-%d %H:%M}建档）"
            direction = "被撞" if d.created_at > c.created_at else "撞"
            pairs.append({
                "target": f"{d.company}（{who}建档·{d.created_at:%m-%d %H:%M}）",
                "direction": direction,
                "fields": c.match_fields(d),
                "confidence": c.match_confidence(d),
            })
        dup.append({
            "id": c.pk,
            "company": c.company,
            "created_at": c.created_at,
            "flagged_at": c.duplicate_flagged_at,
            "owner": owner_text,  # 归属方(先建档,资源归它)
            "dup_pairs": pairs,
        })
    # 我成交的客户(一表化:成交客户卡即成交单;销售/主管在此看办证/建站/回款进度)
    my_deals = Customer.objects.filter(status=CustomerStatus.DEAL, sales=me).order_by("-deal_at")[:20]

    # 组员管理(主管视角):组员名单 + 每人客户数/成交数
    team_stats = []
    if role == "sales_lead" and me.team:
        from django.db.models import Count
        for member in me.team.members.all().order_by("real_name"):
            member_qs = Customer.objects.filter(owner=member)
            team_stats.append({
                "user": member,
                "total": member_qs.count(),
                "deal": member_qs.filter(status=CustomerStatus.DEAL).count(),
            })

    context = dict(
        title="销售数据总览",
        me=me,
        role=role,
        status_groups=status_groups,
        total=my_customers.count(),
        my_total=Customer.objects.filter(owner=me).count() if role == "sales_lead" else my_customers.count(),
        team_stats=team_stats,
        stale=stale,
        duplicates=dup,
        my_deals=my_deals,
    )
    return render(request, "admin/sales_workbench.html", context)


def consult_workbench(request):
    """咨询数据总览——咨询视角聚合:待分配/我的项目/收款支出/建站进度."""
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect("/admin/login/?next=/admin/consult-workbench/")

    # 角色边界:仅咨询/咨询主管/总经办可看咨询数据总览,其他角色直访 302 回自己工作台
    role = getattr(request.user, "role", None)
    if role not in (Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.ADMIN):
        if role in (Role.SALES, Role.SALES_LEAD):
            return redirect(reverse("sales_workbench"))
        return redirect("/admin/")

    me = request.user
    role = getattr(me, "role", None)
    deals = Customer.objects.filter(status=CustomerStatus.DEAL)

    # 待分配成交客户(嘉茵/总经办可见全部待分配,普通咨询不看)
    if role in ("consultant_lead", "admin"):
        pending_assign = deals.filter(consultant__isnull=True).order_by("-deal_at")[:10]
    else:
        pending_assign = Customer.objects.none()

    # 我的成交客户(普通咨询看自己跟进的;嘉茵看全部)——一表化:成交客户卡即办证单
    if role == "consultant":
        my_projects = deals.filter(consultant=me)
    else:
        my_projects = deals.all()

    # 建站进度分布(必须在切片前统计,切片后 QuerySet 不可再 filter)
    progress = {
        "待开始": my_projects.filter(site_progress="not_started").count(),
        "进行中": my_projects.filter(site_progress="in_progress").count(),
        "已完成": my_projects.filter(site_progress__in=["completed_pending", "deployed"]).count(),
    }

    # 切片用于列表展示
    my_projects = my_projects.order_by("-deal_at")[:20]

    context = dict(
        title="咨询数据总览",
        me=me,
        pending_assign=pending_assign,
        my_projects=my_projects,
        progress=progress,
    )
    return render(request, "admin/consult_workbench.html", context)


def tech_workbench(request):
    """技术数据总览——任务池(待领取)/我承接的/进度统计(一表化:数据源=成交客户)."""
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect("/admin/login/?next=/admin/tech-workbench/")
    role = getattr(request.user, "role", None)
    if role not in (Role.TECH, Role.ADMIN):
        return redirect(reverse("dashboard"))

    from apps.customers.models import Customer, CustomerStatus
    from apps.projects.models import SiteProgress

    me = request.user
    deal_base = Customer.objects.filter(status=CustomerStatus.DEAL)
    # 任务池:已勾建站类目/信息(需要建站)且未承接的成交客户
    pool = (deal_base.filter(tech_assigned__isnull=True)
            .exclude(site_category="")
            .exclude(site_category__isnull=True)
            .order_by("deal_at"))
    # 我承接的
    mine = deal_base.filter(tech_assigned=me).order_by("-deal_at")
    # 进度统计
    from django.db.models import Q as _Q
    progress = {
        "待开始": deal_base.filter(site_progress=SiteProgress.NOT_STARTED).count(),
        "进行中": deal_base.filter(site_progress=SiteProgress.IN_PROGRESS).count(),
        "已完成": deal_base.filter(_Q(site_progress=SiteProgress.COMPLETED_PENDING) | _Q(site_progress=SiteProgress.DEPLOYED)).count(),
        "我承接": mine.count(),
    }
    # 总经办(老板)不干活:技术数据总览=部门总览——展示承接分布,不显示个人领取/我承接
    is_admin = role == Role.ADMIN
    all_claimed = deal_base.filter(tech_assigned__isnull=False).order_by("-deal_at") if is_admin else Customer.objects.none()
    context = dict(
        title="技术数据总览",
        me=me,
        role=role,
        pool=pool,
        mine=mine,
        progress=progress,
        is_admin=is_admin,
        all_claimed=all_claimed,
    )
    return render(request, "admin/tech_workbench.html", context)


@login_required
def monitor(request):
    """技术监控后台(独立系统,完全脱离业务):业务系统内(/admin/前缀)任何人访问一律302回业务;独立/ops/后台仅管理层."""

    # 业务系统内(/admin/ 前缀)访问后台 → 任何人(含管理层)302回业务——后台完全独立于业务系统
    if request.path.startswith("/admin/"):
        return redirect("/admin/")
    # 独立后台(/ops/):仅管理层(总经办/系统管理员);业务岗(技术/销售/咨询)302回工作台
    role = getattr(request.user, "role", "")
    if not (getattr(request.user, "is_superuser", False) or role == "admin"):
        if role == "tech":
            return redirect("tech_workbench")
        return redirect("/admin/")

    # 监控数据 SSOT:采集器聚合(资源/DB/日志/会话/访问/健康度),视图只消费,不内联查询
    from .monitoring import collect_metrics
    context = collect_metrics()
    context["title"] = "技术监控后台"
    return render(request, "admin/monitor.html", context)


@login_required
def resolve_dup(request, customer_id):
    """撞单处理:标记非撞单(解除)——清除duplicate_flagged_at,退出待处理(交差)."""

    role = getattr(request.user, "role", "")
    if not (getattr(request.user, "is_superuser", False) or role == "admin"):
        return redirect("/admin/")
    from apps.customers.models import Customer
    try:
        c = Customer.objects.get(pk=customer_id)
        c.duplicate_flagged_at = None
        c.save(update_fields=["duplicate_flagged_at"])
    except Customer.DoesNotExist:
        pass
    return redirect("/admin/dashboard/")
