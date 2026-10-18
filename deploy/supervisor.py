"""Сторож стенда: запускает сервер и сам обновляет его из GitHub.

Раз в CHECK_SECONDS проверяет ветку main; если появились новые коммиты — git pull, установка зависимостей
и перезапуск сервера. Если сервер упал — поднимает его снова. Работает на Windows и Linux, без Docker.

Запуск из корня репозитория:  python deploy/supervisor.py   (Windows: run_windows.bat)
Порт — переменная PORT (по умолчанию 80).
"""
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
BRANCH = os.environ.get("DEPLOY_BRANCH", "main")
CHECK_SECONDS = int(os.environ.get("CHECK_SECONDS", "120"))
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


def stop(p: subprocess.Popen) -> None:
    p.terminate()
    try:
        p.wait(30)
    except subprocess.TimeoutExpired:
        p.kill()


def main() -> None:
    install()
    proc = start()
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
        if remote and local != remote:
            log(f"обновление {local[:7]} → {remote[:7]}")
            out = subprocess.run(["git", "pull", "--ff-only", "origin", BRANCH], cwd=ROOT, capture_output=True, text=True)
            if out.returncode != 0:
                log(f"git pull не прошёл, сервер работает на старой версии: {out.stderr.strip()[:300]}")
                continue
            install()
            stop(proc)
            proc = start()


if __name__ == "__main__":
    main()
