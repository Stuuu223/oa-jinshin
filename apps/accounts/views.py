# -*- coding: utf-8 -*-
"""老板总览面板视图——M5 驾驶舱首页."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
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
        # 技术等无工作台角色:回 admin 首页
        return redirect("/admin/")

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

    # ── 项目与财务 ──
    projects = Project.objects.all()
    total_projects = projects.count()
    site_progress = {
        "待开始": projects.filter(site_progress="not_started").count(),
        "进行中": projects.filter(site_progress="in_progress").count(),
        "已完成": projects.filter(site_progress="done").count(),
    }
    income = projects.annotate(s=Sum("payments__amount")).aggregate(t=Sum("s"))["t"] or Decimal("0")
    expense = projects.annotate(s=Sum("expenses__amount")).aggregate(t=Sum("s"))["t"] or Decimal("0")
    profit = income - expense

    # ── 部门待办 ──
    today = timezone.localdate()
    due_soon = projects.filter(created_at__date__gte=today).count()
    unread_count = Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()
    dept_todos = {
        "销售:待跟进客户": Customer.objects.filter(status=CustomerStatus.LEAD).count(),
        "咨询:待分配项目": projects.filter(consultant__isnull=True).count(),
        "技术:待开始建站": projects.filter(site_progress="not_started").count(),
        "总经办:未读通知": unread_count,
    }

    # ── 撞单提醒(明细:谁和谁撞了哪个单) ──
    dup_customers = Customer.objects.filter(duplicate_flagged_at__isnull=False).order_by("-duplicate_flagged_at")[:10]
    dup_details = []
    for c in dup_customers:
        # 重复方:公司名 + 建档人,一眼看出"张三↔李四撞单"
        dup_targets = []
        for d in c.find_duplicates()[:3]:
            who = d.created_by.real_name if d.created_by else "未知"
            dup_targets.append(f"{d.company}（{who}建档）")
        dup_details.append({
            "company": c.company,
            "created_by": c.created_by.real_name if c.created_by else "未知",
            "flagged_at": c.duplicate_flagged_at,
            "dup_targets": dup_targets or ["（未检出重复方）"],
        })
    # 横幅条数与明细条数同一数据源(标识客户数),避免"2条却显示4条"
    dup_alerts = len(dup_details)

    context = dict(
        self_service=request,
        title="老板总览面板",
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
    """销售工作台——销售视角聚合:我的客户/待跟进/撞单/快捷操作."""
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect("/admin/login/?next=/admin/sales-workbench/")

    # 角色边界:仅销售/销售主管/总经办可看销售工作台,其他角色直访 302 回自己工作台
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

    # 撞单标识客户
    dup = my_customers.filter(duplicate_flagged_at__isnull=False)[:10]

    context = dict(
        title="销售工作台",
        me=me,
        status_groups=status_groups,
        total=my_customers.count(),
        stale=stale,
        duplicates=dup,
    )
    return render(request, "admin/sales_workbench.html", context)


def consult_workbench(request):
    """咨询工作台——咨询视角聚合:待分配/我的项目/收款支出/建站进度."""
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect("/admin/login/?next=/admin/consult-workbench/")

    # 角色边界:仅咨询/咨询主管/总经办可看咨询工作台,其他角色直访 302 回自己工作台
    role = getattr(request.user, "role", None)
    if role not in (Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.ADMIN):
        if role in (Role.SALES, Role.SALES_LEAD):
            return redirect(reverse("sales_workbench"))
        return redirect("/admin/")

    from apps.projects.models import Project

    me = request.user
    role = getattr(me, "role", None)

    # 待分配项目(嘉茵/总经办可见全部待分配,普通咨询不看)
    if role in ("consultant_lead", "admin"):
        pending_assign = Project.objects.filter(consultant__isnull=True).order_by("-deal_at")[:10]
    else:
        pending_assign = Project.objects.none()

    # 我的项目(普通咨询看自己负责的;嘉茵看全部)
    if role == "consultant":
        my_projects = Project.objects.filter(consultant=me)
    else:
        my_projects = Project.objects.all()

    # 建站进度分布(必须在切片前统计,切片后 QuerySet 不可再 filter)
    progress = {
        "待开始": my_projects.filter(site_progress="not_started").count(),
        "进行中": my_projects.filter(site_progress="in_progress").count(),
        "已完成": my_projects.filter(site_progress="done").count(),
    }

    # 切片用于列表展示
    my_projects = my_projects.order_by("-deal_at")[:20]

    context = dict(
        title="咨询工作台",
        me=me,
        pending_assign=pending_assign,
        my_projects=my_projects,
        progress=progress,
    )
    return render(request, "admin/consult_workbench.html", context)
