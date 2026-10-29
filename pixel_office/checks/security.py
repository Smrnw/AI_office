"""Статическая проверка безопасности: правила по тексту файлов и bandit для Python.

error - то, что нельзя отдавать (секреты в коде, выполнение ввода пользователя);
warning - опасный приём, который иногда оправдан.
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

from .report import Finding

CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".html", ".htm", ".jsx", ".tsx", ".php", ".json", ".env", ".yml", ".yaml"}
MAX_FILE = 2 * 1024 * 1024

# (расширения или None для всех, регулярка, уровень, текст замечания)
RULES = [
    (None, r"AKIA[0-9A-Z]{16}", "error", "В коде ключ доступа AWS"),
    (None, r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}", "error", "В коде секретный API-ключ (sk-…)"),
    (None, r"AIza[0-9A-Za-z_\-]{35}", "error", "В коде API-ключ Google"),
    (None, r"gh[pousr]_[A-Za-z0-9]{36}", "error", "В коде токен GitHub"),
    (None, r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "error", "В коде закрытый ключ"),
    (None, r"(?i)\b(password|passwd|secret|api_?key|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]", "warning",
     "Похоже на пароль или ключ прямо в коде — вынесите в настройки или переменные окружения"),
    ({".js", ".mjs", ".cjs", ".html", ".htm", ".jsx", ".ts", ".tsx"}, r"\beval\s*\(", "warning",
     "eval() выполняет строку как код — опасно, если строка приходит от пользователя"),
    ({".js", ".mjs", ".cjs", ".html", ".htm", ".jsx", ".ts", ".tsx"}, r"\bnew\s+Function\s*\(", "warning",
     "new Function() выполняет строку как код"),
    ({".js", ".mjs", ".cjs", ".html", ".htm", ".jsx", ".ts", ".tsx"}, r"\.(innerHTML|outerHTML)\s*\+?=(?!=)[^;\n]*\b(value|input|location\.(search|hash)|params|query)\b",
     "warning", "Ввод пользователя вставляется через innerHTML — возможна XSS; используйте textContent"),
    ({".js", ".mjs", ".cjs", ".html", ".htm"}, r"\bdocument\.write\s*\(", "warning", "document.write() устарел и опасен"),
    ({".html", ".htm"}, r"<script[^>]+src=['\"]http://", "warning", "Скрипт загружается по незащищённому http://"),
    ({".html", ".htm", ".js", ".jsx"}, r"target=['\"]_blank['\"](?![^>]*\brel=)", "warning",
     "Ссылка target=_blank без rel=\"noopener\""),
    ({".py"}, r"\beval\s*\(\s*input\s*\(", "error", "eval(input()) выполняет произвольный код пользователя"),
    ({".py"}, r"\bexec\s*\(\s*input\s*\(", "error", "exec(input()) выполняет произвольный код пользователя"),
    ({".py"}, r"(?i)execute\s*\(\s*f?['\"].*\b(select|insert|update|delete)\b.*(\{|%s?['\"]\s*%|['\"]\s*\+)", "warning",
     "SQL-запрос собирается из строк — возможна SQL-инъекция; используйте параметры запроса"),
    ({".php"}, r"\$_(GET|POST|REQUEST)\[[^\]]+\]\s*\)?\s*;?\s*\?>|echo\s+\$_(GET|POST|REQUEST)", "warning",
     "Ввод пользователя выводится без экранирования — возможна XSS"),
]
_COMPILED = [(ext, re.compile(rx), sev, msg) for ext, rx, sev, msg in RULES]


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def scan_text(text: str, rel: str) -> List[Finding]:
    ext = Path(rel).suffix.lower()
    found: List[Finding] = []
    for exts, rx, sev, msg in _COMPILED:
        if exts is not None and ext not in exts:
            continue
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            found.append(Finding("security", sev, msg, rel, line))
            break                     # одно замечание правила на файл: строки повторов не нужны
    return found


def scan_files(files: List[Path], root: Path) -> List[Finding]:
    out: List[Finding] = []
    for f in files:
        if f.suffix.lower() not in CODE_EXT or not f.is_file() or f.stat().st_size > MAX_FILE:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.extend(scan_text(text, _rel(f, root)))
    return out


def bandit_available() -> bool:
    return importlib.util.find_spec("bandit") is not None


def run_bandit(files: List[Path], root: Path) -> List[Finding]:
    """bandit разбирает Python статически (код не выполняется), поэтому песочница ему не нужна."""
    py = [str(f) for f in files if f.suffix.lower() == ".py" and f.is_file()]
    if not py or not bandit_available():
        return []
    try:
        r = subprocess.run([sys.executable, "-m", "bandit", "-q", "-f", "json", *py],
                           capture_output=True, timeout=120)
        data = json.loads(r.stdout.decode("utf-8", errors="replace") or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    out: List[Finding] = []
    seen: Dict[tuple, bool] = {}
    for item in data.get("results", []):
        sev = str(item.get("issue_severity", "")).upper()
        if sev == "LOW":
            continue
        rel = _rel(Path(item.get("filename", "")), root)
        key = (rel, item.get("test_id"))
        if key in seen:
            continue
        seen[key] = True
        level = "error" if sev == "HIGH" and str(item.get("issue_confidence", "")).upper() == "HIGH" else "warning"
        out.append(Finding("security", level, f"bandit {item.get('test_id')}: {item.get('issue_text', '')}",
                           rel, int(item.get("line_number") or 0)))
    return out
