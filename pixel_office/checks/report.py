"""Результат проверки проекта: список замечаний, скриншоты и итог."""
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

LEVELS = ("error", "warning", "info")


@dataclass
class Finding:
    kind: str           # syntax | tests | browser | security | vision
    level: str          # error - возвращаем на доработку, warning - сообщаем, info - для сведения
    message: str
    file: str = ""
    line: int = 0

    def text(self) -> str:
        where = f"{self.file}:{self.line} " if self.file and self.line else (f"{self.file} " if self.file else "")
        return f"{where}{self.message}".strip()


@dataclass
class Report:
    folder: str
    started_at: float = field(default_factory=time.time)
    findings: List[Finding] = field(default_factory=list)
    steps: Dict[str, str] = field(default_factory=dict)      # шаг -> итог одной строкой
    shots: List[str] = field(default_factory=list)           # имена файлов скриншотов
    sandbox: str = ""

    def add(self, items: List[Finding]) -> None:
        self.findings.extend(items)

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "folder": self.folder,
            "started_at": self.started_at,
            "finished_at": time.time(),
            "ok": not self.errors,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "steps": self.steps,
            "shots": self.shots,
            "sandbox": self.sandbox,
            "findings": [asdict(f) for f in self.findings],
        }

    def summary_for_chat(self, limit: int = 8) -> Dict[str, Any]:
        """Короткая версия для сообщения в чате: итог и самые важные замечания."""
        top = sorted(self.findings, key=lambda f: LEVELS.index(f.level) if f.level in LEVELS else 9)[:limit]
        return {
            "folder": self.folder,
            "ok": not self.errors,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "steps": self.steps,
            "shots": self.shots,
            "items": [{"level": f.level, "kind": f.kind, "text": f.text()} for f in top],
        }
