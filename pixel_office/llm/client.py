"""Единая точка вызова нейросетей: Gemini, Anthropic, любой OpenAI-совместимый API и демо."""
import asyncio
import base64
import ipaddress
from typing import Any, Dict, Optional

import httpx

from .. import config_store, runtime, settings
from ..config_store import ConfigError
from . import demo, usage

RETRYABLE_MARKERS = ("429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED", "UNAVAILABLE",
                     "Timeout", "timed out", "ConnectError", "RemoteProtocolError")
# интерфейс на английском: инструкции у агентов русские, а отвечать они должны по-английски
ENGLISH_NOTE = ("\n\nLANGUAGE: the office works in English. Write every human-readable text in English: "
                "chat replies, task titles and specs, review reasons, code comments and page content. "
                "Keep JSON keys and file names exactly as requested.")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def with_language(system: str) -> str:
    return system + ENGLISH_NOTE if config_store.language() == "en" else system


class Cancelled(Exception):
    """Пользователь нажал СТОП, пока шёл запрос."""


_http: Optional[httpx.AsyncClient] = None
_semaphore: Optional[asyncio.Semaphore] = None


def http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(settings.LLM_TIMEOUT, connect=15))
    return _http


async def close() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.LLM_PARALLEL)
    return _semaphore


def _is_local(url: str) -> bool:
    """Локальная модель (Ollama, LM Studio) ключа не требует: свой компьютер, хост Docker или домашняя сеть."""
    host = httpx.URL(url).host if url else ""
    if host in ("localhost", "host.docker.internal") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def _short_error(r: httpx.Response) -> str:
    """Текст ошибки провайдера без лишнего: сначала пробуем поле message из JSON."""
    try:
        data = r.json()
        err = data.get("error", data) if isinstance(data, dict) else data
        msg = err.get("message") if isinstance(err, dict) else None
        if msg:
            return str(msg)[:220]
    except ValueError:
        pass
    return r.text[:220]


async def _gemini(model_id: str, key: str, system: str, user: str, json_mode: bool, image: Optional[bytes] = None):
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ConfigError("Для Gemini установите пакет google-genai: pip install google-genai")
    client = genai.Client(api_key=key)
    cfg: Dict[str, Any] = {"system_instruction": system}
    if json_mode:
        cfg["response_mime_type"] = "application/json"
    contents: Any = user if image is None else [types.Part.from_bytes(data=image, mime_type="image/png"), user]
    resp = await asyncio.to_thread(client.models.generate_content, model=model_id, contents=contents,
                                   config=types.GenerateContentConfig(**cfg))
    meta = getattr(resp, "usage_metadata", None)
    tokens = None
    if meta is not None and getattr(meta, "prompt_token_count", None) is not None:
        tokens = (int(meta.prompt_token_count or 0), int(getattr(meta, "candidates_token_count", 0) or 0))
    return resp.text or "", tokens


async def _anthropic(url: str, model_id: str, key: str, system: str, user: str, json_mode: bool,
                     image: Optional[bytes] = None):
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    payload = {
        "model": model_id,
        "max_tokens": 8192,
        "system": system + (" Return ONLY valid JSON without markdown." if json_mode else ""),
        "messages": [{"role": "user", "content": user if image is None else [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(image)}},
            {"type": "text", "text": user}]}],
    }
    r = await http().post(url or "https://api.anthropic.com/v1/messages", headers=headers, json=payload)
    if r.status_code != 200:
        raise RuntimeError(f"Anthropic {r.status_code}: {_short_error(r)}")
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    if data.get("stop_reason") == "max_tokens":
        runtime.add_log("✂️ Ответ модели обрезан по лимиту длины, файл может быть неполным")
    return text, usage.usage_numbers(data.get("usage", {}), "input_tokens", "output_tokens")


async def _openai(url: str, model_id: str, key: str, system: str, user: str, json_mode: bool,
                  image: Optional[bytes] = None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system + (" Return ONLY valid JSON." if json_mode else "")},
            {"role": "user", "content": user if image is None else [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _b64(image)}},
                {"type": "text", "text": user}]},
        ],
    }
    r = await http().post(url, headers=headers, json=payload)
    if r.status_code != 200:
        raise RuntimeError(f"API {r.status_code}: {_short_error(r)}")
    data = r.json()
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Неожиданный ответ API: {str(data)[:200]}")
    if choice.get("finish_reason") == "length":
        runtime.add_log("✂️ Ответ модели обрезан по лимиту длины, файл может быть неполным")
    return text, usage.usage_numbers(data.get("usage") or {}, "prompt_tokens", "completion_tokens")


async def _call_once(model_ref: str, system: str, user: str, json_mode: bool,
                     purpose: str, meta: Dict[str, Any], image: Optional[bytes] = None) -> str:
    if runtime.state["cancel_requested"] and purpose != "chat":
        raise Cancelled()
    model = config_store.model_info(model_ref)
    provider = config_store.provider_info(model.get("provider", ""))
    api_type = provider.get("api_type", "openai_compatible")
    key = config_store.provider_key(provider)
    url = (provider.get("base_url") or "").strip()
    model_id = model.get("model_id", "")
    name = provider.get("name", provider["id"])
    system = with_language(system)

    if api_type == "demo":
        text, tokens = await demo.respond(purpose, meta, json_mode), None
    elif api_type == "gemini":
        if not key:
            raise ConfigError(f"Не задан API-ключ для провайдера «{name}» (Настройки → Провайдеры)")
        text, tokens = await _gemini(model_id, key, system, user, json_mode, image)
    elif api_type == "anthropic":
        if not key:
            raise ConfigError(f"Не задан API-ключ для провайдера «{name}» (Настройки → Провайдеры)")
        text, tokens = await _anthropic(url, model_id, key, system, user, json_mode, image)
    else:
        url = url or "https://api.openai.com/v1/chat/completions"
        if not key and not _is_local(url):
            raise ConfigError(f"Не задан API-ключ для провайдера «{name}» (Настройки → Провайдеры)")
        text, tokens = await _openai(url, model_id, key, system, user, json_mode, image)

    if tokens:
        usage.track(model_ref, tokens[0], tokens[1], exact=True)
    else:
        usage.track(model_ref, usage.estimate(system + user), usage.estimate(text))
    return text


async def ping(api_type: str, url: str, key: str, model_id: str) -> str:
    """Проверка связи из мастера настройки: ещё не сохранённые провайдер и модель, один короткий запрос."""
    system, user = "Reply with one word: OK", "ping"
    if api_type == "demo":
        return "OK"
    if not model_id:
        raise ConfigError("Укажите ID модели")
    if api_type == "gemini":
        if not key:
            raise ConfigError("Укажите API-ключ")
        text, _ = await _gemini(model_id, key, system, user, False)
    elif api_type == "anthropic":
        if not key:
            raise ConfigError("Укажите API-ключ")
        text, _ = await _anthropic(url, model_id, key, system, user, False)
    else:
        if not url:
            raise ConfigError("Укажите адрес API (Base URL)")
        if not key and not _is_local(url):
            raise ConfigError("Укажите API-ключ")
        text, _ = await _openai(url, model_id, key, system, user, False)
    return (text or "").strip()[:200]


async def call_llm(model_ref: str, system: str, user: str, json_mode: bool = False,
                   purpose: str = "", meta: Optional[Dict[str, Any]] = None, image: Optional[bytes] = None) -> str:
    """Лимит одновременных запросов и до 3 попыток при 429/5xx/таймаутах.
    purpose и meta нужны только демо-провайдеру, чтобы понять, что от него хотят.
    image - PNG-картинка (скриншот страницы) для моделей, которые умеют смотреть на изображения."""
    meta = meta or {}
    for attempt in range(3):
        try:
            async with _sem():
                return await _call_once(model_ref, system, user, json_mode, purpose, meta, image)
        except (asyncio.CancelledError, Cancelled, ConfigError):
            raise
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            if attempt < 2 and any(m in err for m in RETRYABLE_MARKERS):
                delay = 2 ** (attempt + 1)
                runtime.add_log(f"⏳ Провайдер временно недоступен, повтор через {delay} с ({err[:90]})")
                await asyncio.sleep(delay)
                continue
            raise
    raise RuntimeError("Провайдер не ответил")  # недостижимо, но так понятнее линтеру
