# Развёртывание и проверки на Linux

Целевая среда проекта — Linux AMD64/ARM64. Основной стек запускается Docker Compose; недоверенный код — на выделенном Linux-узле или в отдельной Linux-VM на Linux-хосте. Для Runner базовая среда — Ubuntu 24.04, Python 3.12, systemd 255+ и cgroup v2. Для API и инструментов разработки подходит Python 3.12/3.13; для фронтенда — Node.js 22.12+.

## Запуск продукта через Docker

На Linux-хосте нужны Git, Docker Engine и Compose v2. Python, uv и Node.js на хосте для этого сценария не нужны: конфигурация подготавливается Python-контейнером, фронтенд собирается Node-контейнером, API работают в своих контейнерах.

Из корня checkout сначала соберите образ инструментов/API и подготовьте настройки. Файлы создаются от UID/GID текущего оператора. Существующий `.env` сохраняется, а генератор событий сохраняет существующие сервисные signing keys.

```sh
docker version
docker compose version
docker build -t reverse-hr:local .
test -f .env || docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$PWD:/workspace" --workdir /workspace \
  --entrypoint python reverse-hr:local scripts/configure.py
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$PWD:/workspace" --workdir /workspace \
  --env PYTHONPATH=/workspace/src \
  --entrypoint python reverse-hr:local scripts/configure_events.py
```

Затем запустите фронтенд, API, инфраструктуру и workers:

```sh
docker compose -f compose.yaml -f compose.frontend.yaml --profile all config --quiet
docker compose -f compose.yaml -f compose.frontend.yaml --profile all up --build -d
docker compose -f compose.yaml -f compose.frontend.yaml --profile all ps
```

[Dockerfile фронтенда](../infra/Dockerfile.frontend) выполняет `npm ci` и сборку React. Финальный контейнер содержит статические файлы и Nginx, запускается без root, с read-only filesystem и временным `/tmp`. [Compose override](../compose.frontend.yaml) подключает его к gateway: `/api/candidate/...` проксируется в `/candidate/...`. SPA-маршруты, включая `/auth/callback`, возвращают `index.html`. Vite в Docker-сценарии не запускается.

По умолчанию интерфейс доступен на Linux-хосте по `http://localhost:3000`, Keycloak — `http://localhost:8080`, API — `http://localhost:8000`. Порты привязаны к loopback; для проверки с рабочего компьютера используйте SSH forwarding, описанный ниже. Compose сохраняет данные в именованных volumes; не используйте `down -v`, если нужно сохранить БД и файлы.

```sh
curl --fail http://127.0.0.1:3000/health/live
curl --fail http://127.0.0.1:3000/api/candidate/health/ready
curl --fail http://127.0.0.1:3000/api/assessment/health/ready
curl --fail http://127.0.0.1:3000/api/evaluation/health/ready
docker compose -f compose.yaml -f compose.frontend.yaml --profile all logs --tail=100 frontend gateway
```

Проверка `frontend/health/live` подтверждает раздачу интерфейса; проверки через `/api/` подтверждают маршрутизацию и readiness соответствующего API. Авторизация и продуктовые сценарии требуют отдельной проверки с пользователями, банком заданий и политиками.

API выполняют свои миграции при старте. БД и роли разделены по сервисам. Профиль `all` включает демоадаптеры; внешние LLM, транскрипция, S3 и доставка требуют своей конфигурации. Добавляйте нужные Compose overrides и профили в каждую команду запуска и обновления.

Runner устанавливается и допускается отдельно по [инструкции Linux Runner](../infra/runner/README.md). Обычный контейнер Code Runner в Compose не заменяет доверенную среду NsJail. На одной физической Linux-машине выделите Runner отдельную Linux-VM; установщик рассчитан на выделенный узел. Эта граница исполнения сохраняется и при Docker-развёртывании платформы.

## Разработка с локальными Python и Node.js

Этот альтернативный сценарий нужен для работы с исходниками и локальных тестов. На Linux-хосте установите Python 3.12/3.13, uv и Node.js 22.12+, затем подготовьте настройки:

```sh
uv sync --frozen
test -f .env || uv run python scripts/configure.py
PYTHONPATH=src uv run python scripts/configure_events.py
docker compose --profile all up --build -d
```

## Интерфейс и публикация

В режиме разработки фронтенд можно запустить через Vite:

```sh
cd frontend
npm ci
VITE_BACKEND_MODE=api VITE_DEV_PORT=3000 npm run dev -- --host localhost
```

С рабочего компьютера можно открыть этот стенд через SSH forwarding портов 3000, 8000 и 8080. Например, `ssh -L 3000:127.0.0.1:3000 -L 8000:127.0.0.1:8000 -L 8080:127.0.0.1:8080 user@linux-server`. Адрес браузера тогда — `http://localhost:3000`; стандартный OIDC callback соответствует этому адресу.

Для серверного Docker-развёртывания задайте `FRONTEND_KEYCLOAK_URL=https://auth.example.org` в `.env` до сборки. `FRONTEND_BIND_IP` и `FRONTEND_PORT` задают адрес и порт опубликованного интерфейса; по умолчанию это `127.0.0.1:3000` для внешнего HTTPS reverse proxy на том же Linux-хосте. Если proxy работает на другом узле, задайте достижимый частный адрес и ограничьте доступ соответствующей сетью.

```sh
docker compose -f compose.yaml -f compose.frontend.yaml --profile all up --build -d
```

Публичные `VITE_*` настройки встраиваются в статическую сборку: изменение URL требует пересборки frontend. HTTPS reverse proxy направляет запросы интерфейса на контейнер frontend, который уже обслуживает SPA и `/api/`. Keycloak публикуется отдельно на домене авторизации. TLS-сертификаты и рабочая конфигурация Keycloak не создаются автоматически этим override.

Если фронтенд публикуется отдельно без Docker, соберите его вручную:

```sh
cd frontend
npm ci
VITE_BACKEND_MODE=api \
VITE_API_BASE_URL=/api \
VITE_KEYCLOAK_URL=https://auth.example.org \
npm run build
```

Замените домен примером вашего стенда. Раздавайте `frontend/dist/` внешним Nginx или другим HTTPS reverse proxy с SPA fallback на `index.html`. Маршрут `/api/` должен проксироваться на API gateway с удалением префикса `/api`, например `/api/candidate/v1/...` → `/candidate/v1/...`. Vite dev/preview не является сервером постоянной публикации.

В Keycloak настройте публичный hostname, HTTPS/proxy и redirect URI `https://<домен-интерфейса>/auth/callback` и Web Origins для клиента `reverse-hr-web`. У API настройте соответствующий публичный `HR_OIDC_ISSUER`; внутренний JWKS URL может оставаться адресом Keycloak в Docker-сети. Проверьте разрешённые origins и доступ к callback через внешний proxy. Базовая Compose-конфигурация ориентирована на проверочный стенд; домены, TLS и рабочий режим Keycloak необходимо настроить для серверной эксплуатации.

Провайдеры и хранилища подключаются по профильным инструкциям: [медиа/S3 и backups](media-security.md), [уведомления](external-notifications.md), [резюме/PDF](resume-pdf.md). Mailpit и демоадаптеры используются для проверки, а реальные доставки и интеграции требуют рабочих настроек.

## Проверки бэкенда на Linux

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

SQLite/unit-проверки не подтверждают готовность всех внешних компонентов. Интеграционные проверки PostgreSQL/RabbitMQ запускаются с настройками соответствующих фикстур по [CI](../.github/workflows/backend.yml). Для Runner обязательны реальные Linux probes на установленном узле и актуальный допуск runtime; для PDF/медиа — готовность изолированных декодеров, антивируса и OCR. Пропущенные тесты нужно оценивать по причине пропуска, а не считать пройденными.

## Браузерные тесты на Linux

Базовый `frontend/playwright.config.ts` содержит закреплённый локальный путь браузера. Чтобы сохранить его и запустить проверки на Linux, создайте отдельную конфигурацию в `frontend/playwright.linux.config.ts`:

```ts
import { defineConfig } from '@playwright/test';
import base from './playwright.config';

export default defineConfig({
  ...base,
  use: {
    ...base.use,
    browserName: 'chromium',
    launchOptions: {},
  },
});
```

Затем из `frontend/`:

```sh
npm ci
npx playwright install --with-deps chromium
npm run build
npm test -- --config=playwright.linux.config.ts
```

Установка системных зависимостей Chromium может требовать sudo. Конфигурация сохраняет остальные настройки базового прогона и использует управляемый Playwright Chromium. Базовый прогон запускает Vite в demo-режиме; проверки реальной связки API/OIDC требуют запущенных сервисов, пользователей и настроек соответствующих сценариев. Демо-прогон не заменяет приёмку авторизации и найма с реальным API.

## Обновление Linux-стенда

Пересоберите контейнеры с нужными Compose overrides и профилями; перенос исходников сам по себе не обновляет запущенные образы. Перед обновлением БД подготовьте зарегистрированные резервные копии и проверьте порядок миграций. На Runner изменение исходников, kernel, NsJail или rootfs меняет fingerprint: повторите probes и обновите допуск в Assessment. Старые отчёты проверки описывают конкретные прошлые прогоны и не подтверждают готовность нового узла.

## Автоматическая оценка и генерация

Профиль `all` включает `evaluation-automatic` и `assessment-automatic`. Для внешней модели оценки добавьте профиль `llm`, для генерации по собственным референсам — `generation`. Публичные настройки, ключ провайдера, утверждение референса, калибровка и обновление маршрутов RabbitMQ описаны в [инструкции автоматической оценки](automatic-assessment.md). После изменения кода Runner повторите Linux probes и обновите допуск runtime.
