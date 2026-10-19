# Развёртывание и эксплуатация

Три способа запуска — от самого простого к закрытому контуру банка. Во всех случаях ключи лежат только в файле `.env`
(шаблон — `.env.example`), в git он не попадает.

## 1. Docker Compose — одна команда

```bash
git clone https://github.com/Krackenhell/lct-2026-weak-signals.git && cd lct-2026-weak-signals
cp .env.example .env        # необязательно: без .env система работает в упрощённом режиме
docker compose up -d --build
curl -s http://localhost/api/health   # {"status":"ok"}
```

Открыть `http://<сервер>/`. Порт меняется переменной `HTTP_PORT` в `.env`. Состав: PostgreSQL, backend (FastAPI), интерфейс (nginx).
Контейнеры перезапускаются сами после перезагрузки сервера.

Если с сервера недоступны Docker Hub или npm (так было в Yandex Cloud): зеркало образов в `/etc/docker/daemon.json` —
`{"registry-mirrors": ["https://mirror.gcr.io"]}`, зеркало npm — `NPM_REGISTRY=https://registry.npmmirror.com/` в `.env`.

## 2. Windows без Docker (текущий стенд)

Нужен Python 3.11+. Интерфейс уже собран и лежит в `frontend/dist`, Node.js не нужен.

```bat
git pull
run_windows.bat
```

Скрипт создаёт виртуальное окружение, ставит зависимости и запускает сервер на порту 80 (база — файл SQLite `backend/data/local.db`).
Сервер запускает «сторож» `deploy/supervisor.py`: раз в 2 минуты он проверяет ветку `main` на GitHub, при новых коммитах сам
делает `git pull`, ставит зависимости и перезапускает сервер, а упавший сервер поднимает снова. Журнал — `deploy/supervisor.log`.
Какая версия кода работает, видно в `GET /api/health` (поле `commit`). Порт меняется переменной `PORT`.

## 3. Закрытый контур (без облачных моделей)

Данные запроса не покидают сервер банка, кроме поисковых обращений к открытым источникам.

| Роль | Облачный режим | Закрытый контур |
|---|---|---|
| Decision-модель | Jev (TypeSafe) | Kev-4B (Apache-2.0, тот же API), GPU ~10 ГБ |
| LLM для русских текстов | GigaChat-2 | Qwen3 в Ollama (из списка разрешённых моделей) |
| Стоимость запроса | считается по токенам, см. карточку запроса | 0 ₽ (только сервер) |

```bash
# LLM: профиль offline поднимает Ollama рядом с системой
docker compose --profile offline up -d --build
docker compose exec ollama ollama pull qwen3:8b

# Decision-модель Kev (на машине с GPU)
git clone https://github.com/jaredpalmer/kev.git && cd kev
uv run --extra serve python -m kev.serve --run jaredpalmer/kev-4b --port 8009
```

В `.env`:
```
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://ollama:11434/v1
OPENAI_API_KEY=local
OPENAI_MODEL=qwen3:8b
DECISION_PROVIDER=kev
KEV_BASE_URL=http://<хост с GPU>:8009
```

## 4. Безопасность

- **Токен доступа.** `API_TOKEN=<длинная случайная строка>` — запуск поиска и оценки аналитика требуют заголовок `X-API-Token`
  (в интерфейсе токен вводится один раз). Чтение готовых результатов открыто.
- **Файлы сервера.** Backend отдаёт только файлы из `frontend/dist`; запросы вида `/..%2F.env` получают главную страницу.
- **Ключи** — только в `.env`. Если `.env` мог утечь, ключи GigaChat, TypeSafe, OpenAlex и GitHub нужно перевыпустить.
- **Нагрузка.** Одновременно обрабатываются `MAX_PARALLEL_RUNS` запросов (по умолчанию 2), остальные ждут в очереди;
  повторный клик по той же теме не запускает вторую обработку.

## 5. Скорость

- Повтор темы в течение `REUSE_HOURS` (сутки) открывает готовый результат за секунду; «Пересчитать заново» — новый анализ.
- `PRECOMPUTE_EVERY_HOURS=20` — сервер сам обновляет 6 тем датасета (или `PRECOMPUTE_QUERIES="тема 1;тема 2"`).
  Разово вручную: `cd backend && python -m app.precompute`.
- Новый анализ занимает 5–6 минут; основное время — сбор и проверка источников с соблюдением их лимитов.

## 6. Мониторинг

- `GET /api/health` — живость (для балансировщика и healthcheck Docker).
- `GET /api/metrics` — метрики Prometheus: запуски по статусам, запросы в очереди, среднее время и стоимость запроса,
  вызовы моделей и их задержка, доля сбоев по каждому источнику, оценки аналитиков.
- Журнал вызовов моделей по каждому запросу — вкладка «Журнал» в интерфейсе и `GET /api/runs/{id}/log`.

## 7. REST API

| Метод | Назначение |
|---|---|
| `POST /api/search` `{"query": "...", "use_watchlist": false, "fresh": false}` | запустить анализ (или получить свежий готовый) |
| `GET /api/runs/{id}` | статус, прогресс, сигналы, «наблюдать», исключённые с причинами |
| `GET /api/runs/{id}/export?format=xlsx\|csv\|json\|md` | выгрузка результата |
| `GET /api/candidates/{id}` | досье, паспорт доказательств, источники |
| `POST /api/candidates/{id}/feedback` | оценка аналитика (для дообучения) |
| `GET /api/model` | метрики качества, машина времени, веса модели |

Полное описание с примерами — `http://<сервер>/docs` (Swagger, при запуске backend напрямую на порту 8000).
