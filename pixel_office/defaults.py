"""Стартовая конфигурация: создаётся, только если config.json ещё нет.

Провайдер «demo» работает без ключей и без интернета, чтобы офис можно было
попробовать сразу. Настоящих провайдеров добавляют в Настройках.
"""
from typing import Any, Dict

PROVIDER_TEMPLATES = [
    {"id": "gemini", "name": "Google Gemini", "api_type": "gemini", "api_key": "", "base_url": ""},
    {"id": "anthropic", "name": "Anthropic", "api_type": "anthropic", "api_key": "",
     "base_url": "https://api.anthropic.com/v1/messages"},
    {"id": "openai", "name": "OpenAI", "api_type": "openai_compatible", "api_key": "",
     "base_url": "https://api.openai.com/v1/chat/completions"},
    {"id": "openrouter", "name": "OpenRouter", "api_type": "openai_compatible", "api_key": "",
     "base_url": "https://openrouter.ai/api/v1/chat/completions"},
    {"id": "ollama", "name": "Ollama (локально)", "api_type": "openai_compatible", "api_key": "",
     "base_url": "http://localhost:11434/v1/chat/completions"},
]


DEMO_PROVIDER = {"id": "demo", "name": "Демо (без ключа)", "api_type": "demo", "api_key": "", "base_url": ""}
DEMO_MODEL = {"id": "demo", "name": "Демо-модель", "provider": "demo", "model_id": "demo", "token_limit": 1_000_000}

# что подставить в мастер настройки: пример модели и адрес. Названия моделей меняются - это только подсказка
SETUP_HINTS = {
    "demo": {"model_id": "demo", "base_url": ""},
    "gemini": {"model_id": "gemini-2.5-flash", "base_url": ""},
    "anthropic": {"model_id": "claude-sonnet-5-5", "base_url": "https://api.anthropic.com/v1/messages"},
    "openai": {"model_id": "gpt-4o-mini", "base_url": "https://api.openai.com/v1/chat/completions"},
    "openrouter": {"model_id": "openai/gpt-4o-mini", "base_url": "https://openrouter.ai/api/v1/chat/completions"},
    "ollama": {"model_id": "llama3.1", "base_url": "http://localhost:11434/v1/chat/completions"},
    "custom": {"model_id": "", "base_url": ""},
}


def default_config() -> Dict[str, Any]:
    """Новый офис: только демо-нейросеть, штата нет. При первом запуске интерфейс откроет мастер настройки."""
    return {
        "workspace_dir": "",
        "tasks_dir": "",
        "providers": [dict(DEMO_PROVIDER)],
        "models": [dict(DEMO_MODEL)],
        "agents": [],
        "setup_done": False,
    }

