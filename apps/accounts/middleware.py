# -*- coding: utf-8 -*-
"""会话审计中间件——记录每个 /admin/ 请求的认证状态/user/sessionid 到日志.

用途:自动退出问题定位——下次用户"几分钟退出"时,server.log 有精确铁证:
请求是否带 sessionid、是否认证、user 是谁、UA 是什么,可区分是
浏览器 cookie 丢失 还是 服务端 session 失效。
"""
import logging

logger = logging.getLogger("django.request")


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
            else:
                # auth=NO 时记录完整 COOKIES keys——区分'浏览器没带cookie'(sessionid不在)
                # vs '带了但session失效'(sessionid在,服务端不认)——铁证粒度更细
                ck = ",".join(sorted(request.COOKIES.keys())) or "NONE"
                logger.warning(
                    "AUDIT auth=NO sid=%s path=%s ua=%s cookies=%s",
                    sid[:10], path, ua, ck,
                )
        return self.get_response(request)
