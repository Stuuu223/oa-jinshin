"""金石管理系统 · 通知服务——站内通知统一入口(SSOT).

所有业务流转的通知一律调 notify(),不再散落 Notification.objects.create。
特性:枚举校验 / 防刷屏幂等(同接收人+类型+实体 5 分钟内合并跳过) / 批量接收 / 失败静默(不阻断业务)。
"""
from datetime import timedelta

from django.utils import timezone

from .models import Importance, Notification, NotificationCategory

# 防刷屏窗口:同 (接收人, category, entity) 在该窗口内的重复事件合并/跳过
DEDUP_WINDOW = timedelta(minutes=5)


def notify(
    *,
    category,
    importance=Importance.MEDIUM,
    recipients,
    title,
    content,
    link="",
    actor=None,
    entity_type="",
    entity_id=None,
    dedup=True,
):
    """创建站内通知(可批量)。

    - recipients: User 或 User 列表;为空则直接返回 0(调用方不感知)
    - category/importance: NotificationCategory/Importance 成员或其值(非法抛 ValueError,
      调用方按既有模式 try 兜底,生产环境绝不阻断业务)
    - dedup: 同 (接收人, category, entity_type, entity_id) 在 DEDUP_WINDOW 内已有未处理通知则跳过
      (防刷屏:进度更新等高频事件不会轰炸信息箱)
    - 失败静默:单条创建异常跳过,不影响其余接收人

    返回:实际创建条数
    """
    from .models import User  # 局部导入避免循环引用

    if isinstance(recipients, User):
        recipients = [recipients]
    if not recipients:
        return 0
    if not isinstance(category, NotificationCategory):
        category = NotificationCategory(category)
    if not isinstance(importance, Importance):
        importance = Importance(importance)

    created = 0
    since = timezone.now() - DEDUP_WINDOW
    for user in recipients:
        if not user or not getattr(user, "is_active", False):
            continue
        if dedup and entity_type:
            exists = Notification.objects.filter(
                recipient=user,
                category=category,
                entity_type=entity_type,
                entity_id=entity_id,
                created_at__gte=since,
            ).exists()
            if exists:
                continue
        try:
            Notification.objects.create(
                recipient=user,
                category=category,
                importance=importance,
                actor=actor,
                entity_type=entity_type,
                entity_id=entity_id,
                title=title,
                content=content,
                link=link,
            )
            created += 1
        except Exception:
            # 通知失败静默,绝不阻断业务流转
            continue
    return created
