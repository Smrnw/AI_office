"""Разбор ответов нейросетей: вытаскиваем код и JSON из текста с пояснениями и markdown."""
import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```[\w+\-.#]*[^\S\n]*\n(.*?)```", re.DOTALL)


def extract_code(raw_text: str) -> str:
    text = (raw_text or "").strip()
    blocks = _FENCE_RE.findall(text)
    if blocks:
        # если блоков несколько (код + пример запуска), берём самый большой
        return max(blocks, key=len).strip("\n").rstrip()
    if text.startswith("```"):
        lines = text.splitlines()
        body = lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
        return "\n".join(body).strip()
    return text


def extract_json(raw_text: str) -> Any:
    """Первый валидный JSON-объект или массив в тексте. ValueError, если его нет."""
    text = (raw_text or "").strip()
    for candidate in (text, extract_code(text)):
        try:
            return json.loads(candidate)
        except ValueError:
            pass
    decoder = json.JSONDecoder()
    for m in re.finditer(r"[\[{]", text):
        try:
            value, _ = decoder.raw_decode(text, m.start())
            return value
        except ValueError:
            continue
    raise ValueError("В ответе нейросети не найден JSON")
