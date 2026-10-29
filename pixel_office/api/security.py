"""Защита локального сервера.

Сервер слушает localhost, но любой открытый в браузере сайт может слать ему запросы. Поэтому:
проверяем Host (DNS rebinding), изменяющие запросы принимаем только с Origin нашего хоста и с
заголовком X-Requested-With (без CORS чужой сайт его не поставит), при PIXEL_OFFICE_TOKEN
требуем токен, на страницу офиса ставим строгий CSP.
"""
import hmac
import secrets
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response

from .. import settings

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "pixel-office"
TOKEN_COOKIE = "po_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

# ключ для просмотра сгенерированных страниц: живёт до перезапуска сервера
PREVIEW_KEY = secrets.token_urlsafe(18)

APP_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
           "frame-ancestors 'none'; form-action 'self'")
# сгенерированный агентами код открываем в песочнице: у страницы «пустое» происхождение,
# поэтому она не может дёргать API офиса от имени пользователя
PREVIEW_CSP = "sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads"


def allowed_hosts() -> set:
    hosts = set(LOOPBACK) | set(settings.EXTRA_HOSTS)
    if settings.HOST not in ("0.0.0.0", "::", ""):
        hosts.add(settings.HOST.lower())
    return hosts


def host_name(host_header: str) -> str:
    host = (host_header or "").strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def check_token(value: str) -> bool:
    return bool(settings.ACCESS_TOKEN) and hmac.compare_digest(value or "", settings.ACCESS_TOKEN)


def check_preview_key(value: str) -> bool:
    return hmac.compare_digest(value or "", PREVIEW_KEY)


def _request_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(TOKEN_COOKIE, "")


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if host_name(request.headers.get("host", "")) not in allowed_hosts():
            return PlainTextResponse("Недопустимый Host", status_code=400)

        path = request.url.path
        is_preview = path.startswith("/preview/")

        # /api/health ничего не раскрывает и нужен healthcheck'у Docker, который токена не знает
        if settings.ACCESS_TOKEN and not is_preview and path != "/api/health":
            query_token = request.query_params.get("token", "")
            if path == "/" and check_token(query_token):
                resp = RedirectResponse("/", status_code=303)
                resp.set_cookie(TOKEN_COOKIE, settings.ACCESS_TOKEN, httponly=True, samesite="strict",
                                max_age=30 * 24 * 3600)
                return resp
            if not check_token(_request_token(request)):
                return PlainTextResponse("Нужен токен доступа: откройте адрес вида /?token=ВАШ_ТОКЕН",
                                         status_code=401)

        if request.method not in SAFE_METHODS and path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin is not None and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower():
                return PlainTextResponse("Запрос с чужого сайта отклонён", status_code=403)
            if request.headers.get(CSRF_HEADER, "") != CSRF_VALUE:
                return PlainTextResponse("Нет заголовка X-Requested-With", status_code=403)

        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if is_preview:
            response.headers["Content-Security-Policy"] = PREVIEW_CSP
        else:
            response.headers["Content-Security-Policy"] = APP_CSP
            response.headers["X-Frame-Options"] = "DENY"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif path.startswith("/static/"):
            # после обновления офиса браузер не должен держать старые модули: сверяется по ETag
            response.headers["Cache-Control"] = "no-cache"
        return response
