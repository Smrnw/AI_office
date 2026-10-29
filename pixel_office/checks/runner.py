"""Синтаксис всех файлов и автотесты проекта (pytest для Python, node --test для JavaScript)."""
import re
import shutil
from pathlib import Path
from typing import Dict, List

from . import sandbox
from .report import Finding

PY_TESTS = ("test_*.py", "*_test.py")
JS_TESTS = ("*.test.js", "*.spec.js", "*.test.mjs")


def find_tests(root: Path) -> Dict[str, List[Path]]:
    def collect(patterns):
        found = {p for pat in patterns for p in root.rglob(pat) if p.is_file() and not set(p.parts) & sandbox.SKIP_DIRS}
        return sorted(found)
    return {"python": collect(PY_TESTS), "js": collect(JS_TESTS)}


def _tail(text: str, lines: int = 25) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def run_tests(copy: Path, mode: str) -> Dict:
    """Тесты запускаются в копии проекта. Ни одного теста - не ошибка, но замечание для разработчиков."""
    tests = find_tests(copy)
    findings: List[Finding] = []
    parts: List[str] = []
    if tests["python"]:
        r = sandbox.run(["python", "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
                         "--color=no", "-o", "addopts="], copy, mode, timeout=120)
        m = re.findall(r"(\d+) (passed|failed|error)", r.output)
        counts = {k: int(n) for n, k in m}
        if r.timed_out:
            findings.append(Finding("tests", "error", "Python-тесты не уложились в 2 минуты — возможно, программа ждёт ввода или зациклилась"))
        elif r.code == 5:
            parts.append("pytest: тесты не найдены")
        elif r.code != 0:
            findings.append(Finding("tests", "error", "Python-тесты не прошли:\n" + _tail(r.output)))
        parts.append(f"pytest: прошло {counts.get('passed', 0)}, упало {counts.get('failed', 0) + counts.get('error', 0)}")
    if tests["js"]:
        if mode == "local" and not shutil.which("node"):
            parts.append("node --test: Node.js не установлен")
        else:
            rels = [p.relative_to(copy).as_posix() for p in tests["js"]]
            r = sandbox.run(["node", "--test", *rels], copy, mode, timeout=120)
            passed = re.search(r"# pass (\d+)", r.output)
            failed = re.search(r"# fail (\d+)", r.output)
            if r.timed_out:
                findings.append(Finding("tests", "error", "JS-тесты не уложились в 2 минуты"))
            elif r.code != 0:
                findings.append(Finding("tests", "error", "JS-тесты не прошли:\n" + _tail(r.output)))
            parts.append(f"node --test: прошло {passed.group(1) if passed else 0}, упало {failed.group(1) if failed else 0}")
    has_code = any(copy.rglob("*.py")) or any(copy.rglob("*.js"))
    if not tests["python"] and not tests["js"] and has_code:
        findings.append(Finding("tests", "info", "В проекте нет автотестов"))
        parts.append("автотестов нет")
    return {"findings": findings, "summary": "; ".join(parts) or "нечего тестировать"}
