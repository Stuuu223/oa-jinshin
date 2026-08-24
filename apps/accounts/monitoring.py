"""监控数据服务(SSOT):控制台/运维面板单一数据源——采集器+聚合,参考 Netdata/Grafana 采集-聚合-展示分层.

视图只调 collect_metrics() 消费,模板只渲染;新增监控项 = 新增采集器,不侵入视图/模板.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Max
from django.utils import timezone


def collect_metrics():
    """聚合全部监控指标 → 控制台面板数据(与模板字段一一对应)."""
    now = timezone.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    system = _collect_system()
    activity = _collect_activity(now, today)
    database = _collect_database(today)
    logs = _collect_logs()
    health = _compute_health(system, today)
    return {
        "srv_up": system["srv_up"],
        "sys_info": system["sys_info"],
        "resources": system["resources"],
        **activity,
        **database,
        **logs,
        **health,
    }


def _collect_system():
    """采集器:系统状态——8000 端口监听 + 系统信息 + 资源(psutil)."""
    import socket
    import django
    import sys as _sys

    srv_up = False
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", 8000))
        srv_up = True
    except Exception:
        srv_up = False
    finally:
        s.close()

    sys_info = {
        "django": django.get_version(),
        "python": _sys.version.split()[0],
        "debug": settings.DEBUG,
        "db": settings.DATABASES["default"]["ENGINE"].split(".")[-1],
    }

    import psutil
    cpu = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    disk_pct = 0
    try:
        disk_pct = psutil.disk_usage("/").percent
    except Exception:
        disk_pct = psutil.disk_usage(str(settings.BASE_DIR)[:3] + "/").percent
    uptime_days = (timezone.now().timestamp() - psutil.boot_time()) / 86400
    return {
        "srv_up": srv_up,
        "sys_info": sys_info,
        "resources": {"cpu": cpu, "mem": mem.percent, "disk": disk_pct, "uptime_days": round(uptime_days, 1)},
    }


def _collect_activity(now, today):
    """采集器:会话/访问/被踢/趋势/排行/事件."""
    from apps.customers.models import VisitLog, OperationLog

    return {
        "login_today": OperationLog.objects.filter(action="登录", created_at__gte=today).count(),
        "kick_today": VisitLog.objects.filter(status=302, created_at__gte=today).count(),
        "active_users": VisitLog.objects.filter(created_at__gte=now - timedelta(minutes=5)).values("user__username").distinct().count(),
        "visits_today": VisitLog.objects.filter(created_at__gte=today).count(),
        "top_paths": list(VisitLog.objects.values("path").annotate(c=Count("id")).order_by("-c")[:5]),
        "events": list(VisitLog.objects.filter(status__in=[302, 404, 500]).order_by("-created_at")[:10]),
        "active_list": list(
            VisitLog.objects.filter(created_at__gte=now - timedelta(minutes=5), user__isnull=False)
            .values("user__real_name", "user__username").annotate(last=Max("created_at")).order_by("-last")[:10]
        ),
        "hours": _hourly_trend(now, VisitLog),
        "login_trend": _hourly_trend(now, OperationLog, action="登录"),
        "user_top": list(
            VisitLog.objects.exclude(user__isnull=True).values("user__real_name", "user__username")
            .annotate(c=Count("id")).order_by("-c")[:5]
        ),
    }


def _hourly_trend(now, model, action=None):
    """最近24小时按小时的计数序列."""
    trend = []
    for i in range(23, -1, -1):
        h0, h1 = now - timedelta(hours=i + 1), now - timedelta(hours=i)
        qs = model.objects.filter(created_at__gte=h0, created_at__lt=h1)
        if action:
            qs = qs.filter(action=action)
        trend.append({"label": f"{h1:%H}时", "c": qs.count()})
    return trend


def _collect_database(today):
    """采集器:DB 监控(核心表记录数)+ 业务数据概览."""
    from apps.customers.models import VisitLog, OperationLog, Customer
    from apps.projects.models import Project
    from django.contrib.sessions.models import Session

    return {
        "db_stats": {
            "sessions": Session.objects.count(),
            "visitlog": VisitLog.objects.count(),
            "operationlog": OperationLog.objects.count(),
            "customers": Customer.objects.count(),
            "projects": Project.objects.count(),
        },
        "customers_total": Customer.objects.count(),
        "customers_today": Customer.objects.filter(created_at__gte=today).count(),
        "projects_total": Project.objects.count(),
        "projects_today": Project.objects.filter(created_at__gte=today).count(),
        "site_progress": dict(Project.objects.values_list("site_progress").annotate(c=Count("id"))),
    }


def _collect_logs():
    """采集器:日志流——server.log 尾部(最近20行,ERROR/WARN/INFO 分级)."""
    log_lines = []
    try:
        with open(settings.BASE_DIR / "server.log", "r", encoding="utf-8", errors="ignore") as f:
            tail = f.readlines()[-40:]
        for ln in tail[-20:]:
            level = "INFO"
            if "ERROR" in ln:
                level = "ERROR"
            elif "WARN" in ln or "WARNING" in ln:
                level = "WARN"
            log_lines.append({"level": level, "text": ln.strip()[:110]})
    except Exception:
        log_lines = []
    return {"log_lines": log_lines}


def _compute_health(system, today):
    """健康度总览:服务/资源/错误综合."""
    from apps.customers.models import VisitLog

    err_today = VisitLog.objects.filter(status__in=[404, 500], created_at__gte=today).count()
    res = system["resources"]
    return {
        "err_today": err_today,
        "health": {
            "srv": system["srv_up"],
            "cpu_ok": res["cpu"] < 90,
            "mem_ok": res["mem"] < 90,
            "disk_ok": res["disk"] < 90,
            "err_ok": err_today < 10,
        },
    }
