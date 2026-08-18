"""金石管理系统 · Django 基础配置."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
APPS_DIR = BASE_DIR / "apps"

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-change-in-prod")
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
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
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

SIMPLEUI_HOME_TITLE = "金石管理系统"
SIMPLEUI_HOME_INFO = False
SIMPLEUI_LOGO = ""
SIMPLEUI_DEFAULT_THEME = "light"
# 首页跳转到老板总览面板(simpleui 官方配置)
SIMPLEUI_HOME_PAGE = "/admin/dashboard/"
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
                {"name": "老板总览面板", "url": "/admin/dashboard/", "icon": "fa fa-line-chart"},
                {"name": "销售工作台", "url": "/admin/sales-workbench/", "icon": "fa fa-user-o"},
                {"name": "咨询工作台", "url": "/admin/consult-workbench/", "icon": "fa fa-file-text-o"},
            ],
        },
        {
            "name": "客户管理",
            "icon": "fa fa-address-book",
            "models": [
                {"name": "客户档案", "url": "/admin/customers/customer/", "icon": "fa fa-file-text-o"},
                {"name": "客户池广场", "url": "/admin/customers/customer/?status__exact=pool", "icon": "fa fa-globe"},
                {"name": "回收站", "url": "/admin/customers/recycledcustomer/", "icon": "fa fa-trash-o"},
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
            "models": [
                {"name": "用户", "url": "/admin/accounts/user/", "icon": "fa fa-user"},
                {"name": "部门", "url": "/admin/accounts/department/", "icon": "fa fa-building-o"},
                {"name": "团队", "url": "/admin/accounts/team/", "icon": "fa fa-group"},
            ],
        },
    ],
}

ANONYMOUS_USER_NAME = None

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
