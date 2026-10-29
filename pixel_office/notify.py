"""Уведомления в Telegram и на почту и ответы команде из Telegram.

Ответы принимаем только из чата, указанного в настройках: бот публичный, написать ему может кто угодно.
Токен и пароль хранятся только на сервере, как и API-ключи.
"""
import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

import httpx

from . import config_store, runtime

EVENTS = ("project_done", "autopilot", "errors", "questions")
DEFAULTS: Dict[str, Any] = {
    "telegram": {"enabled": False, "token": "", "chat_id": "", "replies": True},
    "email": {"enabled": False, "host": "", "port": 587, "security": "starttls", "username": "", "password": "",
              "sender": "", "to": ""},
    "events": {e: True for e in EVENTS},
}
TG_API = "https://api.telegram.org/bot{token}/{method}"
TG_LIMIT = 4000
_BG: set = set()
_http: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0))
    return _http


async def close() -> None:
    if _http is not None and not _http.is_closed:
        await _http.aclose()


def _text(v: Any, limit: int) -> str:
    return str(v or "").strip()[:limit]


def options(cfg: Dict[str, Any], old: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Проверенные настройки. Пустой токен или пароль из формы значит «оставить сохранённый»."""
    raw = cfg.get("notify") if isinstance(cfg.get("notify"), dict) else {}
    prev = (old or {}).get("notify") if isinstance((old or {}).get("notify"), dict) else {}
    tg_raw = raw.get("telegram") if isinstance(raw.get("telegram"), dict) else {}
    tg_prev = prev.get("telegram") if isinstance(prev.get("telegram"), dict) else {}
    em_raw = raw.get("email") if isinstance(raw.get("email"), dict) else {}
    em_prev = prev.get("email") if isinstance(prev.get("email"), dict) else {}
    ev_raw = raw.get("events") if isinstance(raw.get("events"), dict) else {}
    try:
        port = max(1, min(65535, int(em_raw.get("port") or 587)))
    except (TypeError, ValueError):
        port = 587
    host, user = _text(em_raw.get("host"), 200), _text(em_raw.get("username"), 200)
    # сохранённый пароль переживает только правку прочих полей: иначе, подменив сервер,
    # можно было бы получить пароль на свой SMTP при авторизации
    same_server = (host, port, user) == (_text(em_prev.get("host"), 200), em_prev.get("port") or 587,
                                         _text(em_prev.get("username"), 200))
    return {
        "telegram": {
            "enabled": _flag(tg_raw.get("enabled"), False),
            "token": _text(tg_raw.get("token"), 200) or _text(tg_prev.get("token"), 200),
            "chat_id": _text(tg_raw.get("chat_id"), 40),
            "replies": _flag(tg_raw.get("replies"), True),
        },
        "email": {
            "enabled": _flag(em_raw.get("enabled"), False),
            "host": host, "port": port,
            "security": em_raw.get("security") if em_raw.get("security") in ("starttls", "ssl", "none") else "starttls",
            "username": user,
            "password": _text(em_raw.get("password"), 200) or (_text(em_prev.get("password"), 200) if same_server else ""),
            "sender": _text(em_raw.get("sender"), 200), "to": _text(em_raw.get("to"), 500),
        },
        "events": {e: _flag(ev_raw.get(e), True) for e in EVENTS},
    }


def _flag(v: Any, default: bool) -> bool:
    return v if isinstance(v, bool) else default


def public(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Для браузера: секреты заменяем флагами «сохранено»."""
    o = options(cfg)
    o["telegram"]["has_token"] = bool(o["telegram"].pop("token"))
    o["email"]["has_password"] = bool(o["email"].pop("password"))
    return o


def _english() -> bool:
    return config_store.language() == "en"


# ---------- отправка ----------

async def send_telegram(token: str, chat_id: str, text: str) -> None:
    r = await _client().post(TG_API.format(token=token, method="sendMessage"),
                             json={"chat_id": chat_id, "text": text[:TG_LIMIT], "disable_web_page_preview": True})
    if r.status_code != 200:
        raise RuntimeError(f"Telegram {r.status_code}: {r.text[:150]}")


def _send_email_sync(o: Dict[str, Any], subject: str, text: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = o["sender"] or o["username"]
    msg["To"] = o["to"]
    msg.set_content(text)
    if o["security"] == "none" and o["username"]:
        raise RuntimeError("без шифрования пароль ушёл бы открытым текстом — выберите STARTTLS или SSL")
    if o["security"] == "ssl":
        server = smtplib.SMTP_SSL(o["host"], o["port"], timeout=20, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(o["host"], o["port"], timeout=20)
    with server:
        if o["security"] == "starttls":
            server.starttls(context=ssl.create_default_context())
        if o["username"]:
            server.login(o["username"], o["password"])
        server.send_message(msg)


async def send_email(o: Dict[str, Any], subject: str, text: str) -> None:
    await asyncio.to_thread(_send_email_sync, o, subject, text)


async def deliver(subject: str, text: str, only: Optional[str] = None) -> List[str]:
    """Отправить во все включённые каналы (или в один - only). Возвращает ошибки по каналам."""
    o = options(config_store.get())
    errors = []
    tg, em = o["telegram"], o["email"]
    if (only in (None, "telegram")) and tg["enabled"] and tg["token"] and tg["chat_id"]:
        try:
            await send_telegram(tg["token"], tg["chat_id"], f"{subject}\n\n{text}")
        except Exception as e:
            errors.append(f"Telegram: {str(e)[:200]}")
    if (only in (None, "email")) and em["enabled"] and em["host"] and em["to"]:
        try:
            await send_email(em, subject, text)
        except Exception as e:
            errors.append(f"Почта: {str(e)[:200]}")
    errors = [_hide_token(e) for e in errors]
    for err in errors:
        runtime.add_log(f"⚠️ Уведомление не отправлено — {err}")
    return errors


def _hide_token(text: str) -> str:
    """Токен бота входит в адрес запроса, а адрес бывает в тексте ошибки. В журнал и в браузер он не попадает."""
    token = options(config_store.get())["telegram"]["token"]
    return text.replace(token, "***") if token else text


def notify(event: str, subject: str, text: str) -> None:
    """Отправить в фоне, не задерживая работу. Выключенные события молча пропускаются."""
    if event not in EVENTS or not options(config_store.get())["events"][event]:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(deliver(subject, text))
    _BG.add(task)
    task.add_done_callback(_BG.discard)


def say(ru: str, en: str) -> str:
    """Текст уведомления на языке офиса (интерфейсный переводчик работает только в браузере)."""
    return en if _english() else ru


def subject(ru: str, en: str) -> str:
    return f"{config_store.office_name()}: " + say(ru, en)


# ---------- ответы из Telegram ----------

async def telegram_loop() -> None:
    """Долгий опрос бота: новые сообщения из разрешённого чата уходят команде, ответы - обратно."""
    from .agents import chat, chat_store

    offset = 0
    while True:
        o = options(config_store.get())["telegram"]
        if not (o["enabled"] and o["replies"] and o["token"] and o["chat_id"]):
            await asyncio.sleep(5)
            continue
        try:
            r = await _client().get(TG_API.format(token=o["token"], method="getUpdates"),
                                    params={"offset": offset, "timeout": 25, "allowed_updates": '["message"]'})
            data = r.json() if r.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            await asyncio.sleep(15)
            continue
        if not data.get("ok"):
            await asyncio.sleep(15)
            continue
        for upd in data.get("result") or []:
            offset = max(offset, int(upd.get("update_id", 0)) + 1)
            msg = upd.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != str(o["chat_id"]) or not msg.get("text"):
                continue                     # чужой чат или не текст - игнорируем
            text = str(msg["text"])[:4000]
            if text.startswith("/start"):
                await _safe_reply(o, ("The office is connected. Write here and the team will reply."
                                      if _english() else "Офис на связи. Пишите сюда — команда ответит."))
                continue
            before = len(chat_store.history(chat_store.TEAM))
            result = chat.send(chat_store.TEAM, text)
            if not result.get("ok"):
                await _safe_reply(o, "⚠️ " + str(result.get("error") or ""))
                continue
            asyncio.get_running_loop().create_task(_forward_replies(o, before))


async def _safe_reply(o: Dict[str, Any], text: str) -> None:
    try:
        await send_telegram(o["token"], o["chat_id"], text)
    except Exception as e:
        runtime.add_log(f"⚠️ Уведомление не отправлено — Telegram: {_hide_token(str(e))[:150]}")


async def _forward_replies(o: Dict[str, Any], before: int, wait: float = 180.0) -> None:
    """Ждём, пока команда ответит в общем чате, и пересылаем ответы агентов в Telegram."""
    from .agents import chat_store

    loop = asyncio.get_running_loop()
    end = loop.time() + wait
    await asyncio.sleep(1)
    while chat_store.TEAM in chat_store.PENDING and loop.time() < end:
        await asyncio.sleep(1)
    replies = [m for m in chat_store.history(chat_store.TEAM)[before:] if m["role"] == "agent"]
    for m in replies:
        files = ", ".join(t["filename"] for t in m.get("tasks") or [])
        await _safe_reply(o, f"[{m.get('author')}] {m['text']}" + (f"\n📌 {files}" if files else ""))
