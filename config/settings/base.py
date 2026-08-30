"""金石管理系统 · Django 基础配置."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
APPS_DIR = BASE_DIR / "apps"

SECRET_KEY = "dev-secret-change-in-prod"  # 写死固定:重启/不同启动环境不导致 session 签名失效(登录丢失)
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "simpleui",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "guardian",
    "simple_history",
    # 自有 app
    "apps.accounts",
    "apps.customers",
    "apps.projects",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "apps.accounts.middleware.SessionRecoveryMiddleware",  # 会话自愈:sessionid被清时用jsbk恢复(在认证前)
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "apps.accounts.middleware.SessionAuditMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]  # 项目静态优先,覆盖 simpleui 主题(black.css 品牌蓝)
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/admin/login/"  # 未登录访问(含独立后台/ops/monitor/)跳业务登录页,避免默认/accounts/login/ 404

SIMPLEUI_HOME_TITLE = "金石管理系统"
SIMPLEUI_HOME_INFO = False
SIMPLEUI_LOGO = ""
SIMPLEUI_DEFAULT_THEME = "light.css"
# 首页跳转到老板总览面板(simpleui 官方配置)
SIMPLEUI_HOME_PAGE = "/admin/dashboard/"
SIMPLEUI_INDEX = "/admin/dashboard/"  # 首页/logo点击跳转目标(缺失时goIndex('')跳转空白)
SIMPLEUI_HOME_ICON = "fa fa-dashboard"
SIMPLEUI_HOME_QUICK = False
SIMPLEUI_HOME_ACTION = False

# 侧边栏自定义菜单——按业务分组,区分客户档案/客户池广场/回收站,避免"长得一样"
SIMPLEUI_CONFIG = {
    "system_keep": False,
    "dynamic": False,  # 只显示下方 menus 配置的菜单,不自动追加未配置模型(避免 auth/group、跟进记录等重复 tab)
    "menu_display": ["工作台", "客户管理", "成交管理", "通知", "系统管理"],
    "menus": [
        {
            "name": "工作台",
            "icon": "fa fa-tachometer",
            "models": [
                {"name": "老板总览面板", "url": "/admin/dashboard/", "icon": "fa fa-line-chart", "permission": "accounts.view_boss_dashboard"},
                {"name": "销售工作台", "url": "/admin/sales-workbench/", "icon": "fa fa-user-o", "permission": "accounts.view_sales_workbench"},
                {"name": "咨询工作台", "url": "/admin/consult-workbench/", "icon": "fa fa-file-text-o", "permission": "accounts.view_consult_workbench"},
                {"name": "建站工作台", "url": "/admin/tech-workbench/", "icon": "fa fa-code", "permission": "accounts.view_tech_workbench"},
            ],
        },
        {
            "name": "客户管理",
            "icon": "fa fa-address-book",
            "permission": "accounts.view_sales_workbench",
            "models": [
                {"name": "我的客户", "url": "/admin/customers/customer/", "icon": "fa fa-file-text-o", "permission": "accounts.view_sales_workbench"},
                {"name": "公司客户池", "url": "/admin/customers/customer/?status__exact=pool", "icon": "fa fa-globe", "permission": "accounts.view_sales_workbench"},
                {"name": "成交客户", "url": "/admin/customers/customer/?status__exact=deal", "icon": "fa fa-check-circle-o", "permission": "accounts.view_sales_workbench",
                 "models": [
                     {"name": "全部", "url": "/admin/customers/customer/?status__exact=deal", "icon": "fa fa-check-circle-o"},
                     {"name": "进行中", "url": "/admin/customers/customer/?status__exact=deal&deal_status=active", "icon": "fa fa-circle-o"},
                     {"name": "已完结", "url": "/admin/customers/customer/?status__exact=deal&deal_status=done", "icon": "fa fa-check-circle"},
                     {"name": "搁置", "url": "/admin/customers/customer/?status__exact=deal&deal_status=on_hold", "icon": "fa fa-pause-circle-o"},
                 ]},
                {"name": "回收站", "url": "/admin/customers/recycledcustomer/", "icon": "fa fa-trash-o", "permission": "accounts.view_sales_workbench"},
                {"name": "操作日志", "url": "/admin/customers/operationlog/", "icon": "fa fa-history", "permission": "accounts.view_user"},
                {"name": "用户行为", "url": "/admin/customers/visitlog/", "icon": "fa fa-eye", "permission": "accounts.view_user"},
            ],
        },
        {
            "name": "成交管理",
            "icon": "fa fa-briefcase",
            "models": [
                {"name": "成交项目", "url": "/admin/projects/project/", "icon": "fa fa-file-o"},
            ],
        },
        {
            "name": "通知",
            "icon": "fa fa-bell-o",
            "models": [
                {"name": "站内通知", "url": "/admin/accounts/notification/", "icon": "fa fa-envelope-o"},
            ],
        },
        {
            "name": "系统管理",
            "icon": "fa fa-cog",
            "permission": "accounts.view_user",
            "models": [
                {"name": "用户", "url": "/admin/accounts/user/", "icon": "fa fa-user", "permission": "accounts.view_user"},
                {"name": "部门", "url": "/admin/accounts/department/", "icon": "fa fa-building-o", "permission": "accounts.view_department"},
                {"name": "团队", "url": "/admin/accounts/team/", "icon": "fa fa-group", "permission": "accounts.view_team"},
            ],
        },
    ],
}

ANONYMOUS_USER_NAME = None

# 会话保持:30 天有效期(登录 Set-Cookie 已验证正确;AUDIT 铁证:退出时 cookies 有 csrftoken 无 sessionid=浏览器端
# sessionid cookie 单独丢失,非服务端——延长有效期减少任何过期边缘;SAVE_EVERY_REQUEST 保持默认 False)
SESSION_COOKIE_AGE = 2592000  # 30 天

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        # 错误日志独立采集(error.log):ERROR/WARN + 异常 traceback 集中,报错可追溯(不淹没在 server.log AUDIT 里)
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "error.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 2,
            "encoding": "utf-8",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {"handlers": ["error_file"], "level": "ERROR", "propagate": False},
        "django.request": {"handlers": ["error_file"], "level": "ERROR", "propagate": False},
        "": {"handlers": ["error_file"], "level": "ERROR"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
}
