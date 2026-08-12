"""金石管理系统 · 账号与权限模型."""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Department(models.Model):
    """部门."""
    name = models.CharField("部门名称", max_length=32, unique=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "部门"
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return self.name


class Role(models.TextChoices):
    """角色枚举——与 01 文档 §1 对齐."""
    SALES = "sales", "销售"
    CONSULTANT = "consultant", "咨询"
    TECH = "tech", "技术"
    FINANCE = "finance", "财务"
    ADMIN = "admin", "管理员"


class User(AbstractUser):
    """扩展用户——取代 Django 自带 auth_user."""
    real_name = models.CharField("姓名", max_length=32)
    role = models.CharField(
        "角色", max_length=16, choices=Role.choices, default=Role.SALES
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="部门",
    )
    entry_date = models.DateField("入职日期", null=True, blank=True, help_text="面试/入职存档，不驱动提成计算")
    position = models.CharField("职务", max_length=16, null=True, blank=True)

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return f"{self.real_name} ({self.get_role_display()})"
