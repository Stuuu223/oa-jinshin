"""生产配置——继承 base,数据库/密钥从环境变量读取(Docker 部署用)。

用法:DJANGO_SETTINGS_MODULE=config.settings.prod + .env 提供 SECRET_KEY/ALLOWED_HOSTS/DATABASE_URL
"""
import environ  # noqa: F401
from .base import *  # noqa: F401,F403

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")  # noqa: F405

SECRET_KEY = env("SECRET_KEY", default="change-me")
DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["106.53.0.44"])

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://jinshi:jinshi@db:5432/jinshi")
}
