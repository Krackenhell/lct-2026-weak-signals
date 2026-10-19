"""Сторож стенда: запускает сервер и сам обновляет его из GitHub.

Раз в CHECK_SECONDS проверяет ветку main; если появились новые коммиты — git pull, установка зависимостей
и перезапуск сервера. Если сервер упал — поднимает его снова. Работает на Windows и Linux, без Docker.

Запуск из корня репозитория:  python deploy/supervisor.py   (Windows: run_windows.bat)
Порт — переменная PORT (по умолчанию 80).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
BRANCH = os.environ.get("DEPLOY_BRANCH", "main")
CHECK_SECONDS = int(os.environ.get("CHECK_SECONDS", "120"))
# Обновляться только на коммит с зелёными проверками GitHub (публичный API, без токена). На период оценки рекомендуется
# DEPLOY_BRANCH=release и DEPLOY_REQUIRE_CI=1: push в main не перезапускает стенд.
REQUIRE_CI = os.environ.get("DEPLOY_REQUIRE_CI", "0") == "1"
REPO = os.environ.get("DEPLOY_REPO", "Krackenhell/lct-2026-weak-signals")
PORT = os.environ.get("PORT", "80")
LOG = ROOT / "deploy" / "supervisor.log"


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120).stdout.strip()


def install() -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=BACKEND, timeout=900)


def start() -> subprocess.Popen:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "APP_COMMIT": git("rev-parse", "--short", "HEAD")}
    log(f"сервер запускается, коммит {env['APP_COMMIT']}, порт {PORT}")
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", PORT], cwd=BACKEND, env=env)


def busy() -> int:
    """Сколько запросов сейчас в очереди и в работе (по метрикам сервера); при ошибке считаем, что занятых нет."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/metrics", timeout=10) as r:
            for line in r.read().decode("utf-8").splitlines():
                if line.startswith("weak_signals_runs_in_progress"):
                    return int(float(line.split()[-1]))
    except (OSError, ValueError):
        pass
    return 0


def wait_idle(max_wait: int = 1200) -> None:
    """Перезапуск не обрывает чужой запрос: ждём, пока обработка закончится (не дольше 20 минут)."""
    waited = 0
    while busy() and waited < max_wait:
        if waited == 0:
            log("обновление ждёт завершения запросов в работе")
        time.sleep(15)
        waited += 15


def ci_green(sha: str) -> bool:
    """Все check-runs коммита завершены успешно (если CI для коммита не настроен — не блокируем)."""
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/commits/{sha}/check-runs", headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            runs = json.loads(r.read().decode("utf-8")).get("check_runs", [])
    except (OSError, ValueError) as exc:
        log(f"проверки CI недоступны ({exc}) — обновление отложено")
        return False
    return all(c.get("status") == "completed" and c.get("conclusion") in ("success", "skipped", "neutral") for c in runs)


def healthy(timeout: int = 90) -> bool:
    """После перезапуска сервер отвечает на /api/health и /api/showcase."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for path in ("/api/health", "/api/showcase"):
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=10) as r:
                    if r.status != 200:
                        raise OSError(f"{path}: {r.status}")
            return True
        except OSError:
            time.sleep(5)
    return False


def stop(p: subprocess.Popen) -> None:
    p.terminate()
    try:
        p.wait(30)
    except subprocess.TimeoutExpired:
        p.kill()


def main() -> None:
    install()
    proc = start()
    bad: set[str] = set()  # коммиты, после которых сервер не поднялся
    while True:
        time.sleep(CHECK_SECONDS)
        if proc.poll() is not None:
            log(f"сервер остановился (код {proc.returncode}) — перезапуск")
            proc = start()
            continue
        try:
            git("fetch", "-q", "origin", BRANCH)
            local, remote = git("rev-parse", "HEAD"), git("rev-parse", f"origin/{BRANCH}")
        except (subprocess.SubprocessError, OSError) as exc:
            log(f"не удалось проверить обновления: {exc}")
            continue
        if remote and local != remote and remote not in bad:
            if REQUIRE_CI and not ci_green(remote):
                continue  # проверки ещё идут или красные — ждём следующего цикла
            log(f"обновление {local[:7]} → {remote[:7]}")
            out = subprocess.run(["git", "pull", "--ff-only", "origin", BRANCH], cwd=ROOT, capture_output=True, text=True)
            if out.returncode != 0:
                log(f"git pull не прошёл, сервер работает на старой версии: {out.stderr.strip()[:300]}")
                continue
            install()
            wait_idle()
            stop(proc)
            proc = start()
            if not healthy():
                # Новая версия не отвечает — откат на прежний коммит; этот коммит больше не берём.
                log(f"после обновления сервер не отвечает — откат на {local[:7]}, коммит {remote[:7]} пропускается")
                bad.add(remote)
                stop(proc)
                subprocess.run(["git", "reset", "--hard", local], cwd=ROOT, capture_output=True, text=True)
                install()
                proc = start()


if __name__ == "__main__":
    main()
