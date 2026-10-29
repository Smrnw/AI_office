"""Запуск кода проекта (тестов) в одноразовой копии.

С Docker - контейнер без сети с лимитами памяти и процессов. Без Docker - обычный процесс с таймаутом
и пустым окружением; файловую систему это не изолирует, поэтому в настройках можно требовать Docker.
"""
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .. import settings

IMAGE = "pixel-office-sandbox:1"
DOCKERFILE = Path(__file__).with_name("sandbox.Dockerfile")
COPY_LIMIT = 50 * 1024 * 1024          # больше в песочницу не копируем
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache"}
OUTPUT_LIMIT = 6000

_docker_cache = {"at": 0.0, "ok": False}


@dataclass
class RunResult:
    code: int
    output: str
    timed_out: bool
    mode: str                          # docker | local


def docker_ready() -> bool:
    """Docker установлен и демон отвечает. Результат помним минуту, чтобы не дёргать docker на каждой задаче."""
    now = time.monotonic()
    if now - _docker_cache["at"] < 60:
        return _docker_cache["ok"]
    ok = False
    if shutil.which("docker"):
        try:
            ok = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True,
                                timeout=8).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
    _docker_cache.update(at=now, ok=ok)
    return ok


def _image_ready() -> bool:
    """Образ песочницы собирается один раз: Python с pytest и Node.js. Сборке сеть нужна, запуску - нет."""
    try:
        if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=15).returncode == 0:
            return True
        r = subprocess.run(["docker", "build", "-t", IMAGE, "-f", str(DOCKERFILE), str(DOCKERFILE.parent)],
                           capture_output=True, timeout=900)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pick_mode(preference: str) -> Optional[str]:
    """auto - Docker, если он есть, иначе обычный процесс; docker - только Docker; local - без Docker.
    None - запускать нельзя (выбран docker, а его нет)."""
    if preference in ("auto", "docker") and docker_ready() and _image_ready():
        return "docker"
    return "local" if preference in ("auto", "local") else None


def make_copy(src: Path) -> Path:
    """Одноразовая копия проекта: что бы ни сделал код, рабочая папка не пострадает."""
    # внутри папки данных, а не во временной папке Windows: в её пути бывает кириллица (имя пользователя),
    # а Docker на Windows с такими путями монтирует папку пустой
    dst = settings.DATA_DIR / "checks" / "_sandbox" / uuid.uuid4().hex[:12]
    total = 0

    def ignore(folder, names):
        nonlocal total
        skipped = set()
        for n in names:
            p = Path(folder) / n
            if n in SKIP_DIRS or p.is_symlink():
                skipped.add(n)
            elif p.is_file():
                total += p.stat().st_size
                if total > COPY_LIMIT:
                    skipped.add(n)
        return skipped

    shutil.copytree(src, dst, ignore=ignore)
    return dst


def drop_copy(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _clean_env() -> dict:
    keep = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "LANG")
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", NO_COLOR="1")
    return env


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            proc.kill()


def run(cmd: List[str], cwd: Path, mode: str, timeout: int = 90) -> RunResult:
    """cmd - команда внутри копии проекта. Первый элемент "python" или "node" подменяется нужным интерпретатором."""
    if mode == "docker":
        full = ["docker", "run", "--rm", "--network", "none", "--memory", "512m", "--cpus", "1",
                "--pids-limit", "256", "--security-opt", "no-new-privileges",
                "-v", f"{cwd}:/work", "-w", "/work", IMAGE] + cmd
        env = None
    else:
        full = [sys.executable if cmd[0] == "python" else (shutil.which(cmd[0]) or cmd[0])] + cmd[1:]
        env = _clean_env()
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(full, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, **kwargs)
    try:
        out, _ = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        out, _ = proc.communicate()
        timed_out = True
    text = (out or b"").decode("utf-8", errors="replace")
    if len(text) > OUTPUT_LIMIT:
        text = text[:OUTPUT_LIMIT // 2] + "\n…\n" + text[-OUTPUT_LIMIT // 2:]
    return RunResult(proc.returncode if not timed_out else -1, text, timed_out, mode)
