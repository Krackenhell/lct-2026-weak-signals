# Развёртывание стенда на сервере

Сервер: `midementiew@89.169.170.106` (Yandex Cloud). Задача — поднять стенд и оставить его работать до конца экспертизы.

## 1. Подготовка сервера
```bash
# Docker (если ещё нет)
command -v docker || curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # затем переподключиться по ssh
```
Проверить, что в группе безопасности Yandex Cloud открыты входящие TCP 80 и 443.

Из Yandex Cloud (ru-central1) недоступны get.docker.com и registry.npmjs.org, частично — Википедия, OpenAlex и GDELT (28.09):
- Docker ставить из пакетов Ubuntu: `sudo apt-get install -y docker.io docker-compose-v2`; образы Docker Hub тянуть через зеркало — `/etc/docker/daemon.json`: `{"registry-mirrors": ["https://mirror.gcr.io"]}`.
- В `.env` добавить `NPM_REGISTRY=https://registry.npmmirror.com/` (целостность пакетов сверяется с package-lock.json).
- Сбои Википедии и OpenAlex не ломают запрос: признаки заменяются нейтральными значениями, в досье есть пометка.

## 2. Код
Репозиторий приватный до 29.09 — клонировать с GitHub-токеном Миши (он коллаборатор):
```bash
sudo mkdir -p /opt/weak-signals && sudo chown $USER /opt/weak-signals
git clone https://github.com/Krackenhell/lct-2026-weak-signals.git /opt/weak-signals
cd /opt/weak-signals
```

## 3. Ключи
Файл `.env` Иван передаёт Мише лично (в git его нет). Положить его в `/opt/weak-signals/.env`.
Обязательные строки: `DECISION_PROVIDER=jev`, `TYPESAFE_API_KEY`, `LLM_PROVIDER=gigachat`, `GIGACHAT_AUTH_KEY`, `OPENALEX_API_KEY`, `OPENALEX_EMAIL`, `GITHUB_TOKEN`, `POSTGRES_PASSWORD` (любой длинный), `HTTP_PORT=80`.
Лишние строки (TELEGRAM_BOT_TOKEN, SERVER_*) не нужны — можно удалить.

## 4. Запуск
```bash
cd /opt/weak-signals
docker compose up -d --build
sleep 10
curl -s http://localhost/api/health          # {"status":"ok"}
curl -s http://localhost/api/model | head -c 300   # "trained": true
```

## 5. Проверка снаружи
- Открыть `http://77.239.111.137:8080/` в браузере — главная «Радар слабых сигналов».
- Запустить запрос «перспективные решения в финтехе», дождаться результата (5–10 мин), открыть любой инсайт.
- Проверить, что GigaChat отвечает с сервера: в карточке сигнала досье на русском с пометкой `gigachat:GigaChat-2`.

## 6. После
- Не останавливать контейнеры. `restart: unless-stopped` поднимет их после перезагрузки.
- **После 29.09 23:59 МСК стенд не трогать** — это правило стоп-кода.
- Прислать Ивану ссылку `http://77.239.111.137:8080/` и результат проверки.
