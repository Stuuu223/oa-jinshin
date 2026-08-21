# -*- coding: utf-8 -*-
"""会话审计中间件——记录每个 /admin/ 请求的认证状态/user/sessionid 到日志.

用途:自动退出问题定位——下次用户"几分钟退出"时,server.log 有精确铁证:
请求是否带 sessionid、是否认证、user 是谁、UA 是什么,可区分是
浏览器 cookie 丢失 还是 服务端 session 失效。
"""
import logging

logger = logging.getLogger("django.request")


class SessionRecoveryMiddleware:
    """会话自愈(架构级根治自动退出):sessionid(HttpOnly)被浏览器清理时,
    用 jsbk(非 HttpOnly,与 csrftoken 同样不被清理)恢复会话并重发 sessionid.
    放 AuthenticationMiddleware 之前:恢复 request.session 后,user 由恢复的 session 重新认证.
    """

    BACKUP = "jsbk"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        bk = request.COOKIES.get(self.BACKUP)
        recovered = False
        stale_backup = False
        # 无 sessionid cookie 但有 jsbk → 用 jsbk 恢复会话(值即 session_key)
        if bk and not request.COOKIES.get(settings.SESSION_COOKIE_NAME):
            try:
                store = request.session.__class__(bk)
                store.load()
                if store.get("_auth_user_id"):
                    request.session = store
                    recovered = True
                else:
                    stale_backup = True  # jsbk 值无效(旧 session),需清理,避免残留旧值
            except Exception:
                stale_backup = True
        response = self.get_response(request)
        max_age = getattr(settings, "SESSION_COOKIE_AGE", 2592000)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            # 已认证且无 jsbk(或刚恢复):写入/刷新 backup(非 HttpOnly,与 csrftoken 同样不被清理)
            if not request.COOKIES.get(self.BACKUP) or recovered:
                response.set_cookie(self.BACKUP, request.session.session_key, max_age=max_age, httponly=False, samesite="Lax")
            # 恢复成功:重发 sessionid(HttpOnly),浏览器下次带 sessionid 保持登录
            if recovered:
                response.set_cookie(settings.SESSION_COOKIE_NAME, request.session.session_key, max_age=max_age, httponly=True, samesite="Lax")
        elif stale_backup:
            # jsbk 无效且未恢复:清理旧 jsbk,等待下次认证时重新写入
            response.delete_cookie(self.BACKUP, path="/")
        return response


class SessionAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/admin/") and not path.startswith("/static/"):
            user = request.user
            authed = bool(user.is_authenticated)
            sid = request.session.session_key or "-"
            ua = (request.META.get("HTTP_USER_AGENT") or "")[:40]
            # 退出事件:访问 admin 却未认证(被踢回登录页前的最后请求)
            if authed:
                logger.warning(
                    "AUDIT auth=yes user=%s sid=%s path=%s ua=%s",
                    getattr(user, "username", "?"), sid[:10], path, ua,
                )
                # 登录留痕:同一 session 首次认证时记录"登录"(用户干了什么都知道)
                if not request.session.get("_login_logged"):
                    try:
                        from apps.customers.models import OperationLog
                        OperationLog.objects.create(
                            user=user, action="登录", target="系统",
                            detail=f"{getattr(user, 'username', '?')} 登录系统",
                        )
                        request.session["_login_logged"] = True
                        request.session.save()
                    except Exception:
                        pass
            else:
                # auth=NO 时记录完整 COOKIES keys——区分'浏览器没带cookie'(sessionid不在)
                # vs '带了但session失效'(sessionid在,服务端不认)——铁证粒度更细
                ck = ",".join(sorted(request.COOKIES.keys())) or "NONE"
                logger.warning(
                    "AUDIT auth=NO sid=%s path=%s ua=%s cookies=%s",
                    sid[:10], path, ua, ck,
                )
        return self.get_response(request)
