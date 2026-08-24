"""金石管理系统 · 客户与公海模型（v2：客户池广场 + 撤销栈式设计）."""
from django.conf import settings
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords


class CustomerStatus(models.TextChoices):
    """客户状态——对应 01 文档 §4.1 状态机."""
    LEAD = "lead", "线索"
    FOLLOWING = "following", "跟进中"
    POOL = "pool", "公海"
    DEAL = "deal", "已成交"
    LOST = "lost", "已流失"


class PoolType(models.TextChoices):
    """公海进入方式——v2 claim 新增：区分自动掉入 vs 客户池广场手动释放.

    两者并行不冲突：AUTO 是后台 cron 30 天未跟进自动掉入；
    SQUARE 是销售/主管/总经办主动释放到客户池广场。
    """
    AUTO = "auto", "自动掉入公海"
    SQUARE = "square", "客户池广场（手动释放）"


class Source(models.TextChoices):
    """客户来源."""
    REFERRAL = "referral", "转介绍"
    INBOUND = "inbound", "主动咨询"
    AD = "ad", "广告投放"
    SQUARE = "square", "客户池广场"
    OTHER = "other", "其他"


class SoftDeleteManager(models.Manager):
    """默认排除已软删除的记录."""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Customer(models.Model):
    """客户档案——唯一建档入口为销售部."""
    company = models.CharField("公司名称", max_length=128, db_index=True)
    contact_name = models.CharField("客户联系人", max_length=32)
    phone = models.CharField("联系电话", max_length=32, db_index=True)
    qualification_interest = models.JSONField(
        "需求资质(可多选)",
        default=list,
        blank=True,
        help_text="客户可同时咨询多个资质,如 ICP + EDI",
    )
    source = models.CharField("来源", max_length=16, choices=Source.choices, default=Source.OTHER)
    quote_amount = models.DecimalField(
        "报价金额", max_digits=12, decimal_places=2, null=True, blank=True,
    )
    note = models.TextField("客户情况/备注", blank=True)
    consulted_at = models.DateField("咨询时间", null=True, blank=True)

    status = models.CharField(
        "状态", max_length=16, choices=CustomerStatus.choices, default=CustomerStatus.LEAD
    )
    pool_type = models.CharField(
        "公海类型", max_length=16, choices=PoolType.choices, null=True, blank=True,
        help_text="30天未跟进自动进公海，或销售手动释放到客户池广场",
    )
    square_released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="square_released_customers",
        verbose_name="广场释放人",
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
    duplicate_flagged_at = models.DateTimeField(
        "撞单标识时间", null=True, blank=True, editable=False,
        help_text="疑似重复已标识",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    deleted_at = models.DateTimeField("删除时间", null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="deleted_customers", verbose_name="删除人",
    )

    objects = SoftDeleteManager()
    all_objects = models.Manager()
    history = HistoricalRecords()

    class Meta:
        verbose_name = "客户"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["status", "owner"]),
            models.Index(fields=["last_follow_at"]),
        ]

    def __str__(self) -> str:
        return self.company

    def find_duplicates(self) -> models.QuerySet:
        """撞单查重(置信度分级)——电话相同=100%高置信度(唯一标识),公司名精确=中;泛称联系人(王总等)无唯一性,不触发.

        对应细则第一页·六、提醒功能:不同销售录入相同客户时弹窗提醒(仅高/中置信度,软查重不拦截).
        """
        from django.db.models import Q

        qs = type(self).objects.exclude(pk=self.pk)
        # 高置信度:电话相同(唯一标识,100%撞)
        phone_hits = qs.filter(phone__iexact=self.phone) if self.phone else qs.none()
        # 中置信度:公司名精确相同
        name_hits = qs.filter(company__iexact=self.company) if self.company else qs.none()
        return phone_hits | name_hits

    @property
    def source_label(self) -> str:
        """来源展示（含广场署名）——细则第一页·五:来源栏自动署名"客户池广场-XX".

        署名由 square_released_by 承担,不污染 source 枚举本身。
        """
        if self.source == Source.SQUARE and self.square_released_by:
            return f"客户池广场-{self.square_released_by.real_name}"
        return self.get_source_display()

    @property
    def follow_staff_display(self):
        """跟进人员多次署名+时间——细则第一页·一:在谁的客户池里自动署名+时间,
        再次分配第二人则二次署名+时间,三次则三次署名+时间.

        按归属历史 seq 依次展示:张三 08-16 / 李四 08-17 / 王五 08-18
        """
        parts = []
        history = self.owner_history.filter(revoked_at__isnull=True).order_by("seq")
        for h in history[:3]:
            who = h.to_user.real_name if h.to_user else "未知"
            when = h.assigned_at.strftime("%m-%d") if h.assigned_at else ""
            parts.append(f"{who} {when}".rstrip())
        return " / ".join(parts) if parts else "—"
    # property 对象不能直接设 short_description,须在底层函数上设置
    follow_staff_display.fget.short_description = "跟进人员"


class RecycledCustomer(Customer):
    """回收站视图（代理模型）——细则第一页·七:总经办查看已删除客户.

    代理模型不建表,仅提供"只看已软删客户"的管理入口;objects 覆盖为全量
    Manager,避免继承 SoftDeleteManager 把已删除行又过滤掉。
    """
    objects = models.Manager()

    class Meta:
        proxy = True
        verbose_name = "回收站客户"
        verbose_name_plural = "回收站（已删除客户）"


class CustomerAttachment(models.Model):
    """客户附图——v2 claim 新增：第一页/第二页均要求'附图'字段.

    Mock 阶段用本地 FileField 占位；生产环境切腾讯云 COS 时只需换 storage backend。
    """
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="attachments", verbose_name="客户"
    )
    file = models.FileField("附图", upload_to="customer_attachments/%Y/%m/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="上传人"
    )
    uploaded_at = models.DateTimeField("上传时间", auto_now_add=True)

    class Meta:
        verbose_name = "客户附图"
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return f"{self.customer.company} 附图 #{self.pk}"


class OwnerHistorySourceType(models.TextChoices):
    """归属流转来源类型."""
    DIRECT_INPUT = "direct_input", "销售直接建档"
    SQUARE = "square", "客户池广场获取"
    MANAGER_ASSIGN = "manager_assign", "销售主管分配"
    BOSS_ASSIGN = "boss_assign", "总经办分配"
    SALES_CLAIM = "sales_claim", "销售自主领取（旧公海通道）"
    AUTO_POOL = "auto_pool", "30天未跟进自动掉入公海"


class CustomerOwnerHistory(models.Model):
    """客户归属变更历史——栈式设计，一表三用.

    用途 1：第一页'跟进人员'多次署名+时间（seq 驱动一次/二次/三次展示）
    用途 2：撤销分配——撤销 = 标记最新一条 revoked_at，owner 恢复为 from_user
    用途 3：客户详情页时间线（建档→分配→转手→撤销→成交），纠纷仲裁依据

    详见 14-老板最新Claim与变更执行清单-v2.md §三 决策 2。
    """
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="owner_history", verbose_name="客户"
    )
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="上一持有人",
        help_text="为空表示这是栈底（首次建档/首次分配）",
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        verbose_name="本次持有人",
    )
    source_type = models.CharField(
        "来源类型", max_length=20, choices=OwnerHistorySourceType.choices
    )
    source_note = models.CharField(
        "来源备注", max_length=64, blank=True,
        help_text="广场场景记录释放人姓名，分配场景记录操作人姓名",
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        verbose_name="操作人",
        help_text="谁触发的这次流转（主管/总经办/销售本人）",
    )
    seq = models.PositiveSmallIntegerField("第几次流转", default=1)
    assigned_at = models.DateTimeField("流转时间", auto_now_add=True)
    revoked_at = models.DateTimeField("撤销时间", null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "客户归属变更历史"
        verbose_name_plural = verbose_name
        ordering = ["customer_id", "seq"]

    def __str__(self) -> str:
        target = self.to_user.real_name if self.to_user else "未知"
        return f"{self.customer.company} 第{self.seq}次 → {target}"


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
    # 跟进时间允许手动选（补录早前的电话/微信沟通），默认当前时刻；
    # 旧字段是 auto_now_add 不可编辑,导致"添加跟进没法选时间"
    created_at = models.DateTimeField("跟进时间", default=timezone.now)

    class Meta:
        verbose_name = "跟进记录"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self) -> str:
        date_str = self.created_at.strftime("%m-%d %H:%M") if self.created_at else ""
        return f"{date_str}  {self.content[:30]}"


class OperationLog(models.Model):
    """提交/操作日志——记录谁在何时提交了什么信息,后台可追溯(审计).

    适用:客户建档/修改/成交/释放/分配等关键提交动作,记录操作人+对象+提交的关键字段。
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        verbose_name="操作人",
    )
    action = models.CharField("动作", max_length=32, default="提交")
    target = models.CharField("对象", max_length=200, blank=True)
    detail = models.TextField("提交信息", blank=True)
    created_at = models.DateTimeField("时间", default=timezone.now)

    class Meta:
        verbose_name = "提交日志"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self) -> str:
        who = self.user.real_name if self.user else "未知"
        return f"{self.created_at:%m-%d %H:%M} {who} {self.action} {self.target[:20]}"


class VisitLog(models.Model):
    """用户行为记录:谁/何时/访问了什么路径/状态码(302=被踢回登录页事件)——行为后台可查,不猜."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="用户")
    path = models.CharField("路径", max_length=255)
    status = models.SmallIntegerField("状态码", default=200)
    method = models.CharField("方法", max_length=10, blank=True)
    ip = models.CharField("IP", max_length=64, blank=True)
    user_agent = models.CharField("设备/浏览器", max_length=255, blank=True)
    session_key = models.CharField("会话", max_length=64, blank=True)
    created_at = models.DateTimeField("时间", auto_now_add=True)

    class Meta:
        verbose_name = "用户行为"
        verbose_name_plural = verbose_name
        ordering = ("-created_at",)
