"""30 天未跟进客户自动掉入公海——此前模型注释声称有 cron,实际无任何调度代码.

用法（Windows 任务计划/Linux crontab 每日调度一次）:
    python manage.py release_stale_customers            # 默认 30 天
    python manage.py release_stale_customers --days 15
"""
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.customers.models import (
    Customer, CustomerOwnerHistory, CustomerStatus, OwnerHistorySourceType, PoolType,
)


class Command(BaseCommand):
    help = "把超过 N 天未跟进的「跟进中」客户自动掉入公海（AUTO），并写入归属历史"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30, help="未跟进天数阈值（默认 30）")
        parser.add_argument("--dry-run", action="store_true", help="只显示将掉入公海的客户,不实际执行")

    def handle(self, *args, **options):
        days = options["days"]
        deadline = timezone.now() - timezone.timedelta(days=days)
        qs = Customer.objects.filter(status=CustomerStatus.FOLLOWING).filter(
            Q(last_follow_at__lt=deadline)
            | Q(last_follow_at__isnull=True, created_at__lt=deadline)
        )
        customers = list(qs.select_related("owner"))
        if options["dry_run"]:
            for c in customers:
                self.stdout.write(f"[DRY] {c.company}（归属:{c.owner.real_name if c.owner else '无'}）")
            self.stdout.write(f"共 {len(customers)} 个客户将于正式执行时掉入公海")
            return
        now = timezone.now()
        for c in customers:
            prev_owner = c.owner
            c.status = CustomerStatus.POOL
            c.pool_type = PoolType.AUTO
            c.owner = None
            c.pool_entered_at = now
            c.updated_at = now
            c.save()
            CustomerOwnerHistory.objects.create(
                customer=c, from_user=prev_owner, to_user=None,
                source_type=OwnerHistorySourceType.AUTO_POOL,
                operator=None, seq=self._next_seq(c),
                source_note=f"{days}天未跟进自动掉入",
            )
            self.stdout.write(f"{c.company} → 公海（原归属:{prev_owner.real_name if prev_owner else '无'}）")
        self.stdout.write(self.style.SUCCESS(f"完成:{len(customers)} 个客户掉入公海"))

    def _next_seq(self, customer):
        last = customer.owner_history.order_by("-seq").first()
        return (last.seq + 1) if last else 1
