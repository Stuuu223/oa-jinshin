"""按角色判定 admin 权限的 Mixin——替代 Django 默认的 per-user 权限表.

背景:种子脚本只建 staff 账号不授 model 权限,默认权限体系下所有非超管员工
登录 admin 一律 403。细则的权限模型是按"角色"定义的（销售只看自己的、
主管看组员+自己、总经办看全部),因此直接以 Role 驱动 admin 权限,
行级范围仍由各 ModelAdmin.get_queryset 控制。
"""
from .models import Role

# ── 各业务的准入角色集合（与细则第一页·三/第二页·权限功能对齐）──
FIRST_PAGE_ROLES = {Role.SALES, Role.SALES_LEAD, Role.ADMIN}
PROJECT_VIEW_ROLES = {
    Role.SALES, Role.SALES_LEAD, Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.TECH, Role.ADMIN,
}
PROJECT_EDIT_ROLES = {Role.CONSULTANT, Role.CONSULTANT_LEAD, Role.TECH, Role.ADMIN}
ADMIN_ONLY = {Role.ADMIN}


class RolePermissionsMixin:
    """在 ModelAdmin 上声明 *_ROLES 集合即可按角色放行,超管直通.

    用法:
        class CustomerAdmin(RolePermissionsMixin, admin.ModelAdmin):
            VIEW_ROLES = FIRST_PAGE_ROLES
            ADD_ROLES = FIRST_PAGE_ROLES
            ...
    """

    VIEW_ROLES: set = set()
    ADD_ROLES: set = set()
    CHANGE_ROLES: set = set()
    DELETE_ROLES: set = set()

    def _role_ok(self, request, roles: set) -> bool:
        user = request.user
        if not (user.is_authenticated and user.is_staff):
            return False
        if user.is_superuser:
            return True
        return getattr(user, "role", None) in roles

    def has_module_permission(self, request):
        allowed = self.VIEW_ROLES | self.ADD_ROLES | self.CHANGE_ROLES | self.DELETE_ROLES
        return self._role_ok(request, allowed)

    def has_view_permission(self, request, obj=None):
        return self._role_ok(request, self.VIEW_ROLES | self.CHANGE_ROLES)

    def has_add_permission(self, request):
        return self._role_ok(request, self.ADD_ROLES)

    def has_change_permission(self, request, obj=None):
        return self._role_ok(request, self.CHANGE_ROLES)

    def has_delete_permission(self, request, obj=None):
        return self._role_ok(request, self.DELETE_ROLES)
