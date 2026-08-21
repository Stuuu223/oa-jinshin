"""金石管理系统 · 成交客户/项目模型（v2 claim 第二页：成交客户信息管理）.

设计要点（对应 14-老板最新Claim与变更执行清单-v2.md 及后续讨论拍板）：
1. 收款/支出做成独立记录表（ProjectPayment/ProjectExpense）而非单个字段，
   兼容单次填写与未来分次到账，无需改表结构。利润 = 收款汇总 - 支出汇总，自动计算。
2. 网站搭建进度只做状态字段（待开始/进行中/已完成），不加"是否需要建站"门槛字段
   ——要不要建站是业务判断，不归系统管。
3. 咨询主管（嘉茵）虽属咨询部门，但权限档位与普通咨询不同，全字段可见，不受"隐藏来源"限制。
4. 技术部可见范围维持"全部项目 + 仅六字段"，不按 assignee 行级过滤（claim 原文未提行级限制，
   沿用 11 号文档"技术 2 人自行协商"的旧决策）。
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords


class SiteProgress(models.TextChoices):
    """网站搭建进度——状态化，不用自由文本，便于后续统计."""
    NOT_STARTED = "not_started", "待开始"
    IN_PROGRESS = "in_progress", "进行中"
    DONE = "done", "已完成"


class SiteCategory(models.TextChoices):
    """网站搭建类目——预设选项(非自由文本),与客户需求资质口径一致."""
    ICP = "ICP", "ICP许可证"
    EDI = "EDI", "EDI许可证"
    ICPEDI = "ICPEDI", "ICPEDI（组合套餐）"
    CORP_SITE = "corp_site", "企业官网"
    CORP_SITE_ICP = "corp_site_icp", "企业官网+备案"
    APP = "app", "APP/小程序"
    OTHER = "other", "其他"


class Project(models.Model):
    """成交客户/项目——对应第二页管理页面.

    从 Customer 成交时自动创建，公司名/联系人/电话/来源/报价金额/销售 做快照，
    避免临时客户信息变动影响已成交项目。
    """
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="projects", verbose_name="客户"
    )

    # ── 快照字段（成交时从 Customer 拷贝，不随原客户记录变动） ──
    company_snapshot = models.CharField("客户公司名称", max_length=128)
    contact_name_snapshot = models.CharField("联系人", max_length=32)
    phone_snapshot = models.CharField("联系方式", max_length=32)
    source_snapshot = models.CharField("客户来源", max_length=64, blank=True)
    quote_amount = models.DecimalField("报价金额", max_digits=12, decimal_places=2, null=True, blank=True)

    # ── 成交业务信息 ──
    deal_business = models.CharField("成交业务", max_length=128, blank=True)
    contract_entity = models.CharField("签约主体", max_length=128, blank=True)
    is_invoiced = models.BooleanField("是否开票", default=False)
    is_tax_included = models.BooleanField("是否含税", default=False)
    note = models.TextField("备注", blank=True)

    # ── 人员署名 ──
    sales = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="sold_projects", verbose_name="销售人员",
    )
    consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="consulting_projects", verbose_name="咨询师",
        help_text="成交时为空，由咨询主管（嘉茵）或总经办分配后填入",
    )

    # ── 时间 ──
    created_at = models.DateTimeField("录入时间", auto_now_add=True)
    deal_at = models.DateTimeField("成交时间", auto_now_add=True)

    # ── 建站信息（咨询师/技术填写） ──
    site_category = models.CharField(
        "网站搭建类目", max_length=64, blank=True, choices=SiteCategory.choices,
        help_text="由成交业务自动带出(如成交业务'ICPEDI 双证办理'→类目ICPEDI),无需手动选择",
    )
    site_info = models.TextField("网站搭建信息", blank=True)
    # ── 站点信息(咨询填写,衔接办证/建站) ──
    site_full_name = models.CharField("网站全称", max_length=128, blank=True)
    site_contact_address = models.CharField("网站联系地址", max_length=255, blank=True)
    site_contact_phone = models.CharField("网站联系电话", max_length=32, blank=True)
    site_contact_email = models.EmailField("网站联系邮箱", blank=True)
    site_domain = models.CharField("域名", max_length=128, blank=True)
    site_icp_number = models.CharField("备案号", max_length=64, blank=True)
    site_progress = models.CharField(
        "网站搭建进度", max_length=16, choices=SiteProgress.choices, default=SiteProgress.NOT_STARTED
    )
    # 技术承接人:技术接单建站时记录,咨询/销售可见'谁接了'、该找谁(建站任务流转留痕)
    tech_assigned = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tech_projects", verbose_name="技术承接人",
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = "成交项目"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["sales"]),
            models.Index(fields=["consultant"]),
        ]

    def __str__(self) -> str:
        return f"{self.company_snapshot}（{self.deal_business or '未填'}）"

    @property
    def total_income(self) -> Decimal:
        """收款汇总——汇总所有 ProjectPayment 记录，兼容单次/分次到账."""
        total = self.payments.aggregate(s=models.Sum("amount"))["s"]
        return total or Decimal("0")

    @property
    def total_expense(self) -> Decimal:
        """支出汇总——汇总所有 ProjectExpense 记录."""
        total = self.expenses.aggregate(s=models.Sum("amount"))["s"]
        return total or Decimal("0")

    @property
    def profit(self) -> Decimal:
        """利润 = 收款汇总 - 支出汇总，自动计算，不落库."""
        return self.total_income - self.total_expense


class ProjectPayment(models.Model):
    """项目收款记录——独立表，兼容单次/分次到账（定金+尾款等）.

    咨询师现阶段只填一条也完全支持，未来分期无需改表结构，直接新增记录即可。
    没有审批环节，只用 simple_history（后续接入）留痕，与方案决策 1（留痕不复核）一致。
    """
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="payments", verbose_name="项目")
    amount = models.DecimalField("金额", max_digits=12, decimal_places=2)
    note = models.CharField("备注", max_length=128, blank=True, help_text="如'定金'/'尾款'")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="填写人（咨询师）"
    )
    recorded_at = models.DateTimeField("填写时间", auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "项目收款记录"
        verbose_name_plural = verbose_name
        ordering = ["recorded_at"]

    def __str__(self) -> str:
        return f"{self.project.company_snapshot} 收款 {self.amount}"


class ProjectExpense(models.Model):
    """项目支出记录——独立表，与 ProjectPayment 同构."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="expenses", verbose_name="项目")
    amount = models.DecimalField("金额", max_digits=12, decimal_places=2)
    note = models.CharField("备注", max_length=128, blank=True, help_text="如'域名费'/'服务器费'")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="填写人（咨询师）"
    )
    recorded_at = models.DateTimeField("填写时间", auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "项目支出记录"
        verbose_name_plural = verbose_name
        ordering = ["recorded_at"]

    def __str__(self) -> str:
        return f"{self.project.company_snapshot} 支出 {self.amount}"


class ProjectConsultantHistory(models.Model):
    """咨询师分配历史——栈式，与 CustomerOwnerHistory 同构，不含撤销（claim 未提）.

    支撑"先进嘉茵，由嘉茵分配，可二次调配并显示第一次记录"。
    """
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="consultant_history", verbose_name="项目"
    )
    from_consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="上一任咨询师", help_text="为空表示首次分配",
    )
    to_consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="+", verbose_name="本次咨询师",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="+", verbose_name="分配人（嘉茵/总经办）",
    )
    seq = models.PositiveSmallIntegerField("第几次分配", default=1)
    assigned_at = models.DateTimeField("分配时间", auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "咨询师分配历史"
        verbose_name_plural = verbose_name
        ordering = ["project_id", "seq"]

    def __str__(self) -> str:
        target = self.to_consultant.real_name if self.to_consultant else "未知"
        return f"{self.project.company_snapshot} 第{self.seq}次 → {target}"


class ProjectAttachment(models.Model):
    """项目附图——对应 claim 第二页'附图'字段."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="attachments", verbose_name="项目")
    file = models.FileField("附图", upload_to="project_attachments/%Y/%m/")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="上传人")
    uploaded_at = models.DateTimeField("上传时间", auto_now_add=True)

    class Meta:
        verbose_name = "项目附图"
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return f"{self.project.company_snapshot} 附图 #{self.pk}"
