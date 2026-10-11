# Структура бэкенда

Схемы компонентов и взаимодействий: [архитектура](architecture-diagrams.md).

Бэкенд — монорепозиторий с отдельными процессами и БД сервисов. Исходники сгруппированы по владельцам; общий образ и lock-файл зависимостей пока сохранены. Перенос файлов не меняет маршруты API, опубликованные OpenAPI-схемы, события, имена БД и идентификаторы миграций.

```text
src/reverse_hr/
  services/
    candidate/
      app.py             # точка запуска, маршруты, readiness
      consumer.py        # обработка входящих событий
      domain/            # профиль, грейды, предпочтения, резюме
      migrations/        # существующая цепочка Candidate
      resume_*.py        # обработка PDF и изолированный декодер
    assessment/
    code_runner/         # также sandbox, supervisor и политики NsJail
    evaluation/
    matching/
    hiring/
    ...                  # остальные сервисы и демоадаптеры
  contracts/             # DTO, события, доказательства и чистая проверка контрактов
  shared/                # JWT, подписи, БД/outbox/inbox, файловое/S3-хранилище
  protocols/             # подписанные RPC-клиенты и внутренние HTTP-адаптеры
  coordination/          # owner-dispatch Privacy и общие процессы review SLA
  platform/              # конфигурация, HTTP/worker bootstrap, lazy registry, Alembic
    migrations/versions/ # только общая транспортная миграция

tests/
  conftest.py            # общие фикстуры
  services/<service>/   # проверки конкретного сервиса
  shared/                # транспорт, контракты, проверки архитектуры
  integration/           # сценарии через несколько сервисов
```

## Правила зависимостей

- Сервис не импортирует реализацию другого сервиса. Общие типы файлов, доски, результатов Runner, снимков тестов и доказательств находятся в `contracts/`.
- `shared/` и `contracts/` не импортируют внутренний код сервисов. В `shared/` нет моделей бизнес-таблиц сервисов или consumers с бизнес-обработчиками.
- `protocols/` реализует межсервисный протокол: подпись, привязку запроса/ответа и внутренние endpoints. Код серверной стороны выполняется в процессе владельца и использует его локальную БД.
- `coordination/` содержит общие процессы с явным выбором владельца: выгрузки/исправления Privacy и review SLA. Модели очередей проверяющих принадлежат соответствующим сервисам. Этот слой не получает доступ к БД другого владельца.
- `platform/registry.py` хранит пути модулей и загружает выбранный сервис/consumer по запросу. Общий транспорт RabbitMQ не импортирует все бизнес-обработчики при старте.

Запрет прямых межсервисных импортов проверяет [test_architecture.py](../tests/shared/test_architecture.py). Полное отсутствие логической связанности из этого не следует: сервисы по-прежнему связаны контрактами и общими процессами. Внутри `domain/` пока сохранены существующие модули с маршрутом, моделью и бизнес-операцией; разделение этих модулей на дополнительные слои потребует отдельного рефакторинга.

## Запуск и миграции

Compose явно указывает точку запуска сервиса, например:

```sh
HR_SERVICE_NAME=candidate PYTHONPATH=src uv run uvicorn \
  reverse_hr.services.candidate.app:create_app --factory --port 8001
```

Сервисная точка запуска проверяет соответствие `HR_SERVICE_NAME`. Общий HTTP bootstrap отвечает за trace ID, обработку ошибок, метрики и вызов readiness выбранного сервиса.

Миграции и фоновый worker запускаются общими техническими командами:

```sh
HR_SERVICE_NAME=candidate PYTHONPATH=src uv run python \
  -m reverse_hr.platform.migrate upgrade head
HR_SERVICE_NAME=candidate PYTHONPATH=src uv run python \
  -m reverse_hr.platform.worker consume
```

Alembic берёт `0001_transport` из `platform/migrations/versions/` и цепочку выбранного сервиса из `services/<service>/migrations/`. Существующие revision IDs и таблицы сохранены: пересоздавать БД для этой реорганизации не нужно. Credentials, RabbitMQ и остальные зависимости подготавливаются по [инструкции Linux](linux-deployment.md).

## Проверки и обновление стенда

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
# Пример отдельного сервиса:
uv run pytest -q tests/services/matching
PYTHONPATH=src uv run python scripts/export_contracts.py
docker compose --profile all config --quiet
```

Образ содержит новые пакеты и миграции внутри `src/`. Старые контейнеры продолжают работать со своим прежним образом до пересборки и перезапуска. Реорганизация сама по себе не обновляет работающий стенд.

Для Linux Runner обновлены supervisor/systemd, provision script, пути гостевого runtime и реальных probes. После обновления исходников на узле нужно повторить проверку и оформить новый допуск runtime: изменение расположения файлов меняет fingerprint. Инструкции — [Runner](../infra/runner/README.md); перенос не отключает проверки изоляции и не продлевает допуск автоматически.
