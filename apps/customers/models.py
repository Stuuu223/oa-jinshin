"""金石管理系统 · 客户与公海模型（v2：客户池广场 + 撤销栈式设计）."""
from django.conf import settings
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.projects.models import SiteCategory, SiteProgress  # 一表化并入(原项目表枚举;项目退役时迁入本模块)


class CustomerStatus(models.TextChoices):
    """客户状态——对应 01 文档 §4.1 状态机."""
    LEAD = "lead", "线索"
    FOLLOWING = "following", "跟进中"
    POOL = "pool", "公司客户池"
    DEAL = "deal", "已成交"
    LOST = "lost", "已流失"


class DealStatus(models.TextChoices):
    """成交客户子状态——成交客户信息管理(进行中/已完结/搁置),仅 status=deal 时有效."""
    ACTIVE = "active", "进行中"
    DONE = "done", "已完结"
    ON_HOLD = "on_hold", "搁置"


class PoolType(models.TextChoices):
    """公海进入方式——v2 claim 新增：区分自动掉入 vs 客户池广场手动释放.

    两者并行不冲突：AUTO 是后台 cron 30 天未跟进自动掉入；
    SQUARE 是销售/主管/总经办主动释放到客户池广场。
    """
    AUTO = "auto", "自动掉入公司客户池"
    SQUARE = "square", "客户池广场（手动释放）"


class Source(models.TextChoices):
    """客户来源."""
    REFERRAL = "referral", "转介绍"
    INBOUND = "inbound", "主动咨询"
    AD = "ad", "广告投放"
    SQUARE = "square", "客户池广场"
    OTHER = "other", "其他"


class CostCategory(models.TextChoices):
    """成本类型——咨询部线上申请成本,总经办审核(细则:域名/服务器/技术费/杂费)."""
    DOMAIN = "domain", "域名"
    SERVER = "server", "服务器"
    TECH = "tech", "技术费"
    MISC = "misc", "杂费"
    OTHER = "other", "其他"


class CostStatus(models.TextChoices):
    """成本申请审核状态——总经办审核通过才计入成本."""
    PENDING = "pending", "待审核"
    APPROVED = "approved", "已通过"
    REJECTED = "rejected", "已驳回"


class SoftDeleteManager(models.Manager):
    """默认排除已软删除的记录."""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Customer(models.Model):
    """客户档案——唯一建档入口为销售部."""
    company = models.CharField("公司名称", max_length=128, db_index=True)
    contact_name = models.CharField("客户联系人", max_length=32)
    phone = models.CharField("联系电话", max_length=32, db_index=True)
    wechat = models.CharField("微信号", max_length=64, blank=True)
    qq = models.CharField("QQ号", max_length=32, blank=True)
    intention = models.PositiveSmallIntegerField(
        "客户意向(1-5星)", null=True, blank=True,
        choices=[(1, "★"), (2, "★★"), (3, "★★★"), (4, "★★★★"), (5, "★★★★★")],
    )
    qualification_interest = models.JSONField(
        "需求资质(可多选)",
        default=list,
        blank=True,
        help_text="客户可同时咨询多个资质,如 ICP + EDI",
    )
    source = models.CharField("来源", max_length=32, default="其他")
    quote_amount = models.DecimalField(
        "报价金额", max_digits=12, decimal_places=2, null=True, blank=True,
    )
    note = models.TextField("客户情况/备注", blank=True)
    consulted_at = models.DateField("咨询时间", null=True, blank=True)

    status = models.CharField(
        "状态", max_length=16, choices=CustomerStatus.choices, default=CustomerStatus.LEAD
    )
    deal_status = models.CharField(
        "成交状态", max_length=16, choices=DealStatus.choices, null=True, blank=True,
        help_text="仅 status=deal 时有效:进行中(active)/已完结(done)/搁置(on_hold)",
    )

    # ===== 成交工作单字段(一表化:原项目表并入——细则第二页"成交客户信息管理";仅 status=deal 生效) =====
    deal_business = models.CharField("成交业务", max_length=128, blank=True)
    contract_entity = models.CharField("签约主体", max_length=128, blank=True,
                                       help_text="成交时确定的合同签约主体(一般=公司名)")
    is_invoiced = models.BooleanField("是否开票", default=False)
    is_tax_included = models.BooleanField("是否含税", default=False)
    deal_at = models.DateTimeField("成交时间", null=True, blank=True)
    sales = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="deal_sales_customers", verbose_name="成交销售",
    )
    consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="deal_consultant_customers", verbose_name="咨询师",
    )
    site_category = models.CharField("建站类目", max_length=24, choices=SiteCategory.choices, blank=True)
    site_info = models.TextField("网站搭建信息", blank=True)
    site_full_name = models.CharField("网站全称", max_length=128, blank=True)
    site_domain_icp = models.TextField("域名与备案", blank=True)
    site_contact_address = models.CharField("网站联系地址", max_length=255, blank=True)
    site_contact_phone = models.CharField("网站联系电话", max_length=32, blank=True)
    site_contact_email = models.EmailField("网站联系邮箱", blank=True)
    site_progress = models.CharField("建站进度", max_length=24, choices=SiteProgress.choices, blank=True)
    tech_assigned = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tech_assigned_deal_customers", verbose_name="承接技术",
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

    def match_confidence(self, other) -> str:
        """撞单置信度(SSOT 单一来源):电话相同=high(100%),公司名精确=medium,仅泛称联系人=low.

        撞单触发只用 high/medium;low(泛称,如"王总")不触发撞单,仅供展示.
        """
        if self.phone and other.phone and self.phone == other.phone:
            return "high"
        if self.company and other.company and self.company == other.company:
            return "medium"
        return "low"

    def match_fields(self, other) -> list:
        """撞单命中字段(SSOT 单一来源):与本客户对比 other 命中的字段说明(含泛称附加展示)."""
        fields = []
        if self.phone and other.phone and self.phone == other.phone:
            fields.append(f"电话「{self.phone}」")
        if self.company and other.company and self.company == other.company:
            fields.append(f"公司名「{self.company}」")
        if self.contact_name and other.contact_name and self.contact_name == other.contact_name:
            fields.append(f"联系人「{self.contact_name}」")
        return fields

    @property
    def source_label(self) -> str:
        """来源展示（含广场署名）——细则第一页·五:来源栏自动署名"客户池广场-XX".

        署名由 square_released_by 承担,不污染 source 枚举本身。
        """
        if self.source == Source.SQUARE and self.square_released_by:
            return f"客户池广场-{self.square_released_by.real_name}"
        # 自由填写的来源(不在枚举内)原样展示;已知枚举值仍映射中文标签
        return dict(Source.choices).get(self.source, self.source)

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

    # ===== 财务派生(细则:收款/支出咨询师填,利润自动计算——SSOT 派生不落库) =====
    @property
    def total_received(self):
        """累计收款(所有收款记录之和)."""
        return self.receipts.aggregate(s=models.Sum("amount"))["s"] or 0

    @property
    def total_cost(self):
        """累计支出(仅统计总经办审核通过的支出——驳回的不计入成本)."""
        return self.costs.filter(status=CostStatus.APPROVED).aggregate(s=models.Sum("amount"))["s"] or 0

    @property
    def profit(self):
        """利润 = 累计收款 − 累计支出(自动计算,永不脏)."""
        return self.total_received - self.total_cost


class Receipt(models.Model):
    """收款记录——挂成交客户(细则:收款由咨询师填写),留痕不复核,创建即知会总经办."""
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="receipts", verbose_name="成交客户")
    amount = models.DecimalField("收款金额", max_digits=12, decimal_places=2)
    note = models.CharField("备注", max_length=128, blank=True, help_text="如'定金'/'尾款'/'全款'")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="recorded_receipts", verbose_name="填写人(咨询师)",
    )
    received_at = models.DateField("收款时间", null=True, blank=True, help_text="实际到账日期")
    created_at = models.DateTimeField("录入时间", auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "收款记录"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.customer.company} 收款 {self.amount}"


class Cost(models.Model):
    """支出/成本记录——挂成交客户(细则:支出由咨询师填写),成本申请需总经办审核通过才计入."""
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="costs", verbose_name="成交客户")
    amount = models.DecimalField("支出金额", max_digits=12, decimal_places=2)
    category = models.CharField("成本类型", max_length=16, choices=CostCategory.choices, default=CostCategory.OTHER)
    note = models.CharField("备注", max_length=128, blank=True, help_text="如'域名费'/'服务器费'/'技术费'")
    status = models.CharField("审核状态", max_length=16, choices=CostStatus.choices, default=CostStatus.PENDING)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="recorded_costs", verbose_name="申请/填写人(咨询师)",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_costs", verbose_name="审核人(总经办)",
    )
    reviewed_at = models.DateTimeField("审核时间", null=True, blank=True)
    created_at = models.DateTimeField("申请时间", auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "支出记录"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.customer.company} 支出 {self.amount}"


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
    DEAL_BACK_MY = "deal_back_my", "成交转回我的客户"
    DEAL_BACK_POOL = "deal_back_pool", "成交转回公司客户池"


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
