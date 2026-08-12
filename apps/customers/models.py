"""金石管理系统 · 客户与公海模型."""
from django.conf import settings
from django.db import models


class CustomerStatus(models.TextChoices):
    """客户状态——对应 01 文档 §4.1 状态机."""
    LEAD = "lead", "线索"
    FOLLOWING = "following", "跟进中"
    POOL = "pool", "公海"
    DEAL = "deal", "已成交"
    LOST = "lost", "已流失"


class Source(models.TextChoices):
    """客户来源."""
    REFERRAL = "referral", "转介绍"
    INBOUND = "inbound", "主动咨询"
    AD = "ad", "广告投放"
    OTHER = "other", "其他"


class SoftDeleteManager(models.Manager):
    """默认排除已软删除的记录."""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Customer(models.Model):
    """客户档案——唯一建档入口为销售部."""
    company = models.CharField("公司名称", max_length=128, db_index=True)
    contact_name = models.CharField("对接人", max_length=32)
    phone = models.CharField("联系电话", max_length=32, db_index=True)
    qualification_interest = models.CharField(
        "需求资质",
        max_length=32,
        choices=[
            ("动漫网文", "动漫网文"),
            ("表演网文", "表演网文"),
            ("音乐网文", "音乐网文"),
            ("游戏文网文", "游戏文网文"),
            ("混合网文", "混合网文"),
            ("ICP许可证", "ICP许可证"),
            ("EDI许可证", "EDI许可证"),
            ("ICPEDI", "ICPEDI（组合套餐）"),
            ("广播证", "广播电视节目制作经营许可证"),
        ],
        blank=True,
    )
    source = models.CharField("来源", max_length=16, choices=Source.choices, default=Source.OTHER)
    note = models.TextField("客户情况", blank=True)
    consulted_at = models.DateField("咨询时间", null=True, blank=True)

    status = models.CharField(
        "状态", max_length=16, choices=CustomerStatus.choices, default=CustomerStatus.LEAD
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="归属销售",
        related_name="customers",
    )
    pool_entered_at = models.DateTimeField("进入公海时间", null=True, blank=True)
    last_follow_at = models.DateTimeField("最近跟进时间", null=True, blank=True)
    lost_reason = models.CharField("流失原因", max_length=255, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_customers",
        verbose_name="建档人",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    deleted_at = models.DateTimeField("删除时间", null=True, blank=True, db_index=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        verbose_name = "客户"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["status", "owner"]),
            models.Index(fields=["last_follow_at"]),
        ]

    def __str__(self) -> str:
        return self.company


class FollowUp(models.Model):
    """跟进记录."""
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="follow_ups", verbose_name="客户"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="跟进人"
    )
    content = models.TextField("跟进内容")
    next_follow_at = models.DateTimeField("下次跟进提醒", null=True, blank=True)
    created_at = models.DateTimeField("跟进时间", auto_now_add=True)

    class Meta:
        verbose_name = "跟进记录"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self) -> str:
        date_str = self.created_at.strftime("%m-%d %H:%M") if self.created_at else ""
        return f"{date_str}  {self.content[:30]}"
