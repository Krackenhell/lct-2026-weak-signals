# Радар слабых сигналов — ЛЦТ 2026, задача Газпромбанк.Тех

Сервис по открытому запросу («перспективные решения в финтехе», «кибербезопасность ИИ»…) находит в открытых источниках **ранние научно-технологические тренды**, отделяет их от зрелых технологий, стандартов и маркетингового шума и формирует **топ-15 слабых сигналов** с объяснением, уверенностью модели и проверяемыми источниками.

**Ключевая идея.** Признаки слабого сигнала извлекает decision-модель **Jev** (TypeSafe AI; использование согласовано с экспертами Газпромбанк.Тех) или её локальный аналог **Kev**. Она за один проход отвечает вероятностями на 10 вопросов о текстах источников: «есть ли массовое внедрение», «это стандарт», «это маркетинговый шум»… Итоговое решение принимает **наш интерпретируемый классификатор**, обученный на датасете организатора и собственной выборке отрицательных примеров. Каждая позиция в выдаче объясняется вкладами признаков.

- [Архитектура и методология](docs/architecture.md)
- [Decision-модели: Jev, Kev, Laya](docs/decision-models.md)
- [Разъяснения организатора](docs/organizer-clarifications.md)

## Быстрый старт (Docker)

Требуется Docker с Compose v2.

```bash
git clone https://github.com/Krackenhell/lct-2026-weak-signals.git
cd lct-2026-weak-signals
cp .env.example .env        # при необходимости укажите ключи моделей
docker compose up -d --build
```

Откройте http://localhost (порт меняется переменной `HTTP_PORT`).

Без ключей система работает полностью: decision-модель — на словарных правилах (`DECISION_PROVIDER=heuristic`), досье — по шаблону (`LLM_PROVIDER=none`). Для полного качества укажите в `.env`:

| Переменная | Значение |
|---|---|
| `DECISION_PROVIDER=jev` + `TYPESAFE_API_KEY` | Jev (облачный API TypeSafe) |
| `DECISION_PROVIDER=kev` + `KEV_BASE_URL` | Локальный Kev (см. ниже) |
| `LLM_PROVIDER=gigachat` + `GIGACHAT_AUTH_KEY` | Досье и резюме на русском через GigaChat 2 |
| `LLM_PROVIDER=yandexgpt` + `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` | YandexGPT 5 |
| `OPENALEX_API_KEY`, `GITHUB_TOKEN` | Повышенные лимиты источников (необязательно) |

Проверка: `curl http://localhost/api/health` → `{"status":"ok"}`.

## Развёртывание стенда на сервере

Рекомендуемая конфигурация: Ubuntu 22.04/24.04, 4 vCPU, 8–16 ГБ RAM, 40 ГБ SSD, публичный IP, открыт порт 80. GPU не нужна.

```bash
curl -fsSLO https://raw.githubusercontent.com/Krackenhell/lct-2026-weak-signals/main/deploy/setup-ubuntu.sh
bash setup-ubuntu.sh            # первый запуск создаст /opt/weak-signals/.env — заполните ключи
bash setup-ubuntu.sh            # второй запуск соберёт и поднимет стенд
```

Контейнеры перезапускаются автоматически (`restart: unless-stopped`), в том числе после перезагрузки сервера.

## Локальная разработка без Docker

```bash
# backend (Python 3.11+); по умолчанию SQLite в backend/data/local.db
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend (Node 20+), в другом терминале
cd frontend
npm install
npm run dev          # http://localhost:5173, /api проксируется на :8000
```

## Обучение и оценка модели (этап 1)

```bash
cd backend
python -m app.ml.train            # сбор доказательств для 240 примеров (~30 мин, с кэшем) + обучение
python -m app.ml.train --reask    # переопросить decision-модель по сохранённым доказательствам (например, после подключения Jev)
python -m app.ml.train --refit    # только переобучить классификатор
```

Результаты: `backend/data/model/signal_model.json` (веса), `metrics.json` (Precision / Recall / F1, абляция, перенос на новую область), `training_rows.json` и `training_evidence.json` (признаки и доказательства для воспроизводимости). Отчёт также на странице «Методология и качество».

## Локальный Kev (необязательно)

```bash
git clone https://github.com/jaredpalmer/kev.git && cd kev
uv sync --extra serve
uv run --extra serve python -m kev.serve --run jaredpalmer/kev-4b --port 8009
```

Затем `DECISION_PROVIDER=kev` и `KEV_BASE_URL=http://<хост>:8009`.

## Структура

```
backend/app/collectors   сбор данных: arXiv, OpenAlex, GDELT, GitHub, Hacker News, Википедия
backend/app/pipeline     кандидаты, доказательства, признаки, правила исключения, оркестратор
backend/app/decision     decision-модели: Jev / Kev (System One API), офлайн-правила
backend/app/ml           классификатор, обучение и оценка
backend/app/llm          GigaChat / YandexGPT / OpenAI-совместимые, задачи для LLM
backend/app/api          REST API
backend/data/seed        датасет организатора (JSON), поисковые фразы, отрицательные примеры
backend/data/model       обученная модель и отчёт о метриках
frontend                 веб-интерфейс (React + Vite)
```

## Как работаем вдвоём

Оба участника пишут код по очереди. Состояние всегда в `main`: после каждого завершённого шага — коммит и push, чтобы работу можно было продолжить с любого компьютера. Ключи API хранятся только в `.env`, он не попадает в git.
