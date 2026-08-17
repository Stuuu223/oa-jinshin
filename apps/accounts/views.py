# -*- coding: utf-8 -*-
"""老板总览面板视图——M5 驾驶舱首页."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.models import Notification, User
from apps.customers.models import Customer, CustomerStatus
from apps.projects.models import Project, ProjectExpense, ProjectPayment


def dashboard(request):
    """总览面板:线索→成交漏斗/回款/利润/各部门待办/撞单提醒."""
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect_to_login(request.get_full_path())

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

    # ── 撞单提醒 ──
    dup_alerts = Notification.objects.filter(title="撞单提醒", read_at__isnull=True).count()

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
    )
    return render(request, "admin/dashboard.html", context)


def notification_unread(request):
    """侧边栏信息箱未读徽标数据接口——返回当前用户未读数 JSON."""
    from django.http import JsonResponse

    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"count": 0})
    count = Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()
    return JsonResponse({"count": count})
