#!/usr/bin/env bash
# Развёртывание стенда на чистом Ubuntu 22.04/24.04 (VK Cloud, Cloud.ru, Yandex Cloud).
# Запуск на сервере:  bash setup-ubuntu.sh <git-url> [ветка]
set -euo pipefail

REPO_URL="${1:-https://github.com/Krackenhell/lct-2026-weak-signals.git}"
BRANCH="${2:-main}"
APP_DIR="/opt/weak-signals"

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Установка Docker"
  # get.docker.com недоступен из части российских облаков — тогда пакеты Ubuntu.
  curl -fsSL -m 20 https://get.docker.com | sh || { sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2; }
  sudo usermod -aG docker "$USER" || true
fi

echo "==> Код приложения в $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  sudo git -C "$APP_DIR" fetch --all && sudo git -C "$APP_DIR" checkout "$BRANCH" && sudo git -C "$APP_DIR" pull
else
  sudo git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

if [ ! -f .env ]; then
  sudo cp .env.example .env
  echo "!!! Заполните ключи в $APP_DIR/.env и запустите скрипт ещё раз"
  exit 1
fi

echo "==> Сборка и запуск"
sudo docker compose up -d --build
sleep 5
curl -fsS "http://localhost:${HTTP_PORT:-80}/api/health" && echo " <- стенд работает"
