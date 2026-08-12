"""金石管理系统 · 仿真种子数据（开发用——假公司名/假电话，非真实数据）."""
import os
import random
import sys
from datetime import date, timedelta

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.accounts.models import Department, Role, User  # noqa: E402
from apps.customers.models import Customer, CustomerStatus, Source, FollowUp  # noqa: E402
from django.utils import timezone  # noqa: E402

# ── 公司名素材 ──
COMPANIES = [
    "星辰科技", "云帆网络", "九州文化", "盛世传媒", "银河互动",
    "未来数码", "东方明珠", "凤凰信息", "天马影业", "龙腾数据",
    "蓝海软件", "金盾安全", "万象互娱", "青藤教育", "嘉华咨询",
    "华宇地产", "瑞通物流", "德恒医疗", "中科创投", "星辰大海",
]
QUALIFICATIONS = ["动漫网文", "ICP许可证", "EDI许可证", "表演网文", "广播证", "音乐网文", "ICPEDI"]
FIRST_NAMES = ["张", "李", "王", "赵", "陈", "周", "吴", "郑", "孙", "马"]
LAST_NAMES = ["伟", "芳", "娜", "敏", "静", "强", "磊", "洋", "艳", "涛"]

print("🌱 生成仿真种子数据...")

# ── 部门 ──
depts = {}
for name in ["销售部", "咨询部", "技术部", "财务部"]:
    d, _ = Department.objects.get_or_create(name=name)
    depts[name] = d

# ── 用户（每角色 2-3 人）──
users = {}
for role_tag, role_val, dept_name, count in [
    ("admin1", Role.ADMIN, "销售部", 1),
    ("admin2", Role.ADMIN, "销售部", 1),
    ("sales1", Role.SALES, "销售部", 1),
    ("sales2", Role.SALES, "销售部", 1),
    ("consult1", Role.CONSULTANT, "咨询部", 1),
    ("consult2", Role.CONSULTANT, "咨询部", 1),
    ("tech1", Role.TECH, "技术部", 1),
    ("tech2", Role.TECH, "技术部", 1),
    ("finance1", Role.FINANCE, "财务部", 1),
]:
    u, created = User.objects.get_or_create(
        username=role_tag,
        defaults={
            "real_name": f"仿真-{role_tag}",
            "role": role_val,
            "department": depts[dept_name],
            "is_staff": True,
            "is_superuser": (role_val == Role.ADMIN),
            "entry_date": date.today() - timedelta(days=random.randint(30, 900)),
        },
    )
    if created:
        u.set_password("admin123")
        u.save()
    users[role_tag] = u

# ── 客户（25 条，覆盖五种状态）──
statuses = list(CustomerStatus.values)
for i in range(25):
    company = f"{random.choice(COMPANIES)}{random.choice(['有限公司', '科技', '网络科技', '文化传媒'])}"
    contact = f"{random.choice(FIRST_NAMES)}{random.choice(LAST_NAMES)}"
    phone = f"1{random.randint(30, 99):02d}{random.randint(10000000, 99999999)}"
    status = random.choices(statuses, weights=[3, 4, 4, 3, 1], k=1)[0]

    owner = None
    if status in (CustomerStatus.LEAD, CustomerStatus.FOLLOWING, CustomerStatus.DEAL):
        owner = random.choice([users["sales1"], users["sales2"]])
    if status == CustomerStatus.POOL:
        owner = None

    c = Customer.objects.create(
        company=company,
        contact_name=contact,
        phone=phone,
        qualification_interest=random.choice(QUALIFICATIONS),
        source=random.choice(list(Source.values)),
        note=f"仿真客户 #{i+1}——来源于种子脚本",
        consulted_at=date.today() - timedelta(days=random.randint(1, 120)),
        status=status,
        owner=owner,
        pool_entered_at=timezone.now() if status == CustomerStatus.POOL else None,
        last_follow_at=timezone.now() - timedelta(days=random.randint(0, 60)) if status != CustomerStatus.LEAD else None,
        created_by=random.choice([users["sales1"], users["sales2"]]),
    )
    # 随手加 1-3 条跟进记录
    for j in range(random.randint(1, 3)):
        FollowUp.objects.create(
            customer=c,
            user=owner or users["sales1"],
            content=f"仿真跟进 #{j+1}：与 {contact} 进行了沟通。",
            created_at=timezone.now() - timedelta(days=random.randint(0, 30)),
        )

print(f"✅ 完成：{Department.objects.count()} 部门 / {User.objects.count()} 用户 / {Customer.objects.count()} 客户 / {FollowUp.objects.count()} 跟进记录")
print("   默认密码: admin123")
print("   测试账号: admin1(老板) / sales1 / consult1 / tech1 / finance1")
