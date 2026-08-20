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


class Team(models.Model):
    """销售组/咨询组——v2 claim 新增：支撑"主管看组员+自己"的行级权限.

    对应 14-老板最新Claim与变更执行清单-v2.md §四。lead 字段指向组长
    （销售主管 / 咨询主管，如"嘉茵"）。
    """
    name = models.CharField("团队名称", max_length=32)
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="teams", verbose_name="所属部门"
    )
    lead = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_teams",
        verbose_name="组长/主管",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "团队"
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return f"{self.name}（{self.department.name}）"


class Role(models.TextChoices):
    """角色枚举——v2 claim 更新：拆出销售主管/咨询主管两档.

    - SALES / SALES_LEAD：对应第一页"销售职员""销售主管"
    - CONSULTANT / CONSULTANT_LEAD：对应第二页"咨询师""咨询主管"（如嘉茵）
    - ADMIN：总经办/管理层，超级权限
    """
    SALES = "sales", "销售"
    SALES_LEAD = "sales_lead", "销售主管"
    CONSULTANT = "consultant", "咨询"
    CONSULTANT_LEAD = "consultant_lead", "咨询主管"
    TECH = "tech", "技术"
    FINANCE = "finance", "财务"
    ADMIN = "admin", "总经办/管理员"


# 主管角色集合，供权限过滤复用
LEAD_ROLES = {Role.SALES_LEAD, Role.CONSULTANT_LEAD}


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
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
        verbose_name="所属团队",
        help_text="主管可查看本组组员客户",
    )
    is_team_lead = models.BooleanField(
        "是否团队主管", default=False, help_text="冗余标记，便于权限判断无需反查 Team.lead"
    )
    entry_date = models.DateField("入职日期", null=True, blank=True, help_text="面试/入职存档，不驱动提成计算")
    position = models.CharField("职务", max_length=16, null=True, blank=True)

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = verbose_name
        permissions = [
            ("view_boss_dashboard", "可看老板总览面板"),
            ("view_sales_workbench", "可看销售工作台"),
            ("view_consult_workbench", "可看咨询工作台"),
        ]

    def __str__(self) -> str:
        return f"{self.real_name} ({self.get_role_display()})"


class Notification(models.Model):
    """站内信息箱——对应细则第一页·六"且发送到总经办信息箱（明显的未读数量标识）".

    用途:撞单提醒/分配/撤销等系统事件推送给接收人。ADMIN 首页徽标按 unread_count 展示。
    """
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications", verbose_name="接收人"
    )
    title = models.CharField("标题", max_length=128)
    content = models.CharField("内容", max_length=500)
    link = models.CharField("跳转链接", max_length=255, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    read_at = models.DateTimeField("已读时间", null=True, blank=True)

    class Meta:
        verbose_name = "站内通知"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"[{self.recipient.real_name}] {self.title}"

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self) -> None:
        if not self.read_at:
            from django.utils import timezone

            self.read_at = timezone.now()
            self.save(update_fields=["read_at"])
