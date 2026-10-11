# Изолированный Linux Runner

Runner работает на отдельном нативном Linux AMD64/ARM64 узле. API в обычном
Compose не исполняет код. Docker socket, privileged-контейнер и интерпретатор
хоста не используются. Платформа также разворачивается на Linux; Runner размещается
на выделенном узле или в отдельной Linux-VM на Linux-хосте. Общая инструкция —
[развёртывание на Linux](../../docs/linux-deployment.md).

Узел запускает три worker: `execute`, `validate`, `grade-tests`. Перед каждым
запуском supervisor выполняет все 12 проверок `tests/services/code_runner/test_sandbox_live.py` и
сохраняет приватную запись проверки, связанную с UUID узла, исходниками,
зависимостями, kernel, NsJail, rootfs и cgroup. Пропуск проверки, ошибка или
изменение отпечатка закрывает исполнение. Таймер повторяет запуск через 12 часов.

Профиль: Python 3.12/SQLite; read-only rootfs и workspace; user/pid/net/mount/
ipc/uts namespaces; deny-by-default seccomp; память 128 MiB без swap, один
процесс, CPU 2 секунды, wall time 3 секунды, watchdog 5 секунд, файл до 1 MiB,
32 FD, tmpfs 8 MiB/128 inodes, совокупный вывод до 64 KiB. Код кандидата не
управляет этими параметрами. Системные вызовы для AMD64 и ARM64 заданы отдельными
политиками Kafel.

## Установка

Нужны выделенный Linux с systemd 255+, cgroup v2 (cpu/memory/pids), Python 3.12,
пользователь `runner` без root и проверенная сборка NsJail. Базовая конфигурация —
Ubuntu 24.04; используется закреплённая сборка официального [NsJail](https://github.com/google/nsjail) commit
`4ff54a6e0d5b65a0e1633d6e2fd1425ba6c882ce`, с закреплённым submodule Kafel.
Собирайте на той же архитектуре, на которой будет работать узел:

```sh
sudo apt-get update
sudo apt-get install build-essential git pkg-config bison flex libprotobuf-dev \
  protobuf-compiler libnl-route-3-dev python3.12-venv
git clone https://github.com/google/nsjail.git /tmp/nsjail-reviewed
git -C /tmp/nsjail-reviewed checkout 4ff54a6e0d5b65a0e1633d6e2fd1425ba6c882ce
git -C /tmp/nsjail-reviewed submodule update --init --recursive
make -C /tmp/nsjail-reviewed -j2
 sha256sum /tmp/nsjail-reviewed/nsjail
```

Перед установкой создайте системного пользователя, если его ещё нет:

```sh
id runner >/dev/null 2>&1 || sudo useradd --system --user-group --home-dir /var/lib/reverse-hr-runner --shell /usr/sbin/nologin runner
```

Оператор должен проверить исходники и результат сборки, затем передать конкретный
SHA-256 установщику из checkout проекта на выделенном Linux-узле:

```sh
sudo python3.12 scripts/provision_runner.py \
  --nsjail /tmp/nsjail-reviewed/nsjail --nsjail-sha256 <проверенный-sha256>
sudo mkdir -p /run/systemd/system/reverse-hr-runner.service.d
sudo tee /run/systemd/system/reverse-hr-runner.service.d/verify.conf >/dev/null <<'UNIT'
[Service]
ExecStart=
ExecStart=/opt/reverse-hr-runner/.venv/bin/python -m reverse_hr.services.code_runner.runner_node --verify-only
Restart=no
UNIT
sudo systemctl daemon-reload
sudo systemctl start reverse-hr-runner.service
sudo journalctl -u reverse-hr-runner.service --no-pager
```

Установщик создаёт root-owned артефакты, минимальный rootfs без site-packages,
закреплённый manifest, зависимости по hash lock, приватный scratch и постоянный
UUID узла. Он не переносит ключи платформы и не включает очереди автоматически.
Повторная установка поверх существующих артефактов запрещена.

Отдельная `reverse-hr-runner-scope.service` удерживает стабильный inode cgroup.
Обе службы находятся в выделенном `reverse-hr-runner.slice`. Root pre-start
выдаёт пользователю runner разрешение переноса процессов только внутри этой slice
(`cgroup.procs` и `cgroup.threads`), не затрагивая system.slice, корень cgroup или
контроллеры ресурсов. Перезапуск workers сохраняет scope для очистки незавершённых
попыток. Останавливать scope при активных попытках нельзя.

## Подключение платформы

После проверки оператор задаёт `/etc/reverse-hr-runner/service.env` (root, 0600):

```dotenv
HR_DATABASE_URL=postgresql+psycopg://code_runner:<password>@<private-db>:5432/code_runner
HR_EVENT_PRIVATE_KEY_FILE=/var/lib/reverse-hr-runner/signing.key
HR_EVENT_PUBLIC_KEYS_FILE=/var/lib/reverse-hr-runner/public-keys.json
HR_PRIVACY_API_URL=http://<private-privacy>:8000
HR_ASSESSMENT_API_URL=http://<private-assessment>:8000
HR_WORKSPACE_API_URL=http://<private-workspace>:8000
HR_EVALUATION_API_URL=http://<private-evaluation>:8000
```

Signing key и public-keys должны принадлежать runner, иметь mode 0600 и находиться
в приватном каталоге состояния. Нужны ключ только Code Runner и доступ только к
его БД; ключи других сервисов не передаются. API вызываются по внутренним адресам
без gateway; запросы и ответы проверяются существующим протоколом подписи.

Режим БД переключается существующим CLI `reverse_hr.services.code_runner.runner_control execution
--if-match-version <актуальная-версия>` с окружением Code Runner. CLI блокирует
переключение при неочищенных попытках или конфликте версии. Diagnostic worker в
Compose не исполняет задания в режиме execution. Outbox и consumer платформы
продолжают работать в Compose с настроенным RabbitMQ.

Для допуска закреплённых скрытых тестов Assessment требует отдельной записи
`ASSESSMENT_TRUSTED_RUNTIMES`: policy_id, node_id и fingerprint из probes.json,
approved_at и expires_at (не более семи дней). После изменения артефактов нужна
новая явная проверка и новая политика; неподходящий отпечаток закрывает допуск.
Запись probe сама по себе не утверждает runtime policy и не калибрует грейды.

После настройки удалить только временный verify.conf, выполнить daemon-reload,
запустить Runner и включить refresh.timer. Supervisor прекращает остальные
очереди при падении любого worker. Секреты и диагностические исключения не
печатаются в журнал. Экспортируйте архивные logs без приватных конфигураций.

## Результаты и восстановление

Попытка привязана к конкретному подписанному снимку и admission. Отмена, отзыв
доступа и Privacy deletion блокируют дальнейшее выполнение. Результат сохраняется
только после физически подтверждённой очистки; technical_error не становится
нулевым баллом. Recovery использует постоянные flock и тот же cgroup scope,
останавливает процессы и фиксирует cleanup до ACK Privacy. Lease expiry не
считается доказательством очистки. При сбое недоступный вывод не восстанавливается
повторным выполнением исходного кода.

На каждом целевом Linux-узле нужно выполнить все реальные probes и оформить
допуск для его архитектуры и fingerprint. Проверка другого узла не переносится
на новый сервер. [Исторический отчёт проверки](LOCAL-VERIFICATION.md) фиксирует
результаты конкретного тестового стенда; это не допуск текущего развёртывания
и не независимый аудит возможности выхода из sandbox.

## Подключение к закрытой Docker-сети на Linux

Сеть `backend` в Compose остаётся internal. Runner на другом Linux-узле не может
обращаться к Docker DNS напрямую. Для него настройте закрытый mTLS-мост на
Linux-хосте платформы. Если внутренняя инфраструктура уже предоставляет защищённые
адреса БД и четырёх API, можно использовать их напрямую в `service.env` вместо моста.

Мост допускает TLS 1.3 с клиентским сертификатом и точным SHA-256 сертификата
Runner. Назначения фиксированы: PostgreSQL 15432, Privacy 18001, Assessment 18002,
Workspace 18003, Evaluation 18004. На стороне Runner клиент слушает только
127.0.0.1; гостевой код изолирован своим network namespace и seccomp.

На Linux-хосте платформы подготовьте сертификаты:

```sh
PYTHONPATH=src uv run python scripts/configure_runner_tls.py --node-id <uuid-из-probes>
```

Настройте в `.env` `RUNNER_BIND_IP` — частный адрес Linux-хоста, достижимый с Runner,
и `RUNNER_LINUX_UID`/`RUNNER_LINUX_GID` — числовые UID/GID владельца серверных TLS-файлов.
Сгенерированный `RUNNER_CLIENT_CERT_SHA256` сохраняется установщиком конфигурации.
Создайте локальный `compose.runner-linux.yaml`:

```yaml
services:
  runner-bridge:
    image: python:3.12.12-slim
    user: "${RUNNER_LINUX_UID:?}:${RUNNER_LINUX_GID:?}"
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    mem_limit: 128m
    cpus: 0.5
    pids_limit: 16
    restart: unless-stopped
    environment:
      PYTHONDONTWRITEBYTECODE: "1"
      RUNNER_CLIENT_CERT_SHA256: ${RUNNER_CLIENT_CERT_SHA256:?}
    volumes:
      - ./infra/runner/orbstack_tunnel.py:/tunnel.py:ro
      - ./.secrets/runner-tls-server:/certificates:ro
    command: [python, /tunnel.py, server, --certificates, /certificates]
    networks: [backend, runner-link]
    ports:
      - "${RUNNER_BIND_IP:?}:15432:15432"
      - "${RUNNER_BIND_IP:?}:18001:18001"
      - "${RUNNER_BIND_IP:?}:18002:18002"
      - "${RUNNER_BIND_IP:?}:18003:18003"
      - "${RUNNER_BIND_IP:?}:18004:18004"
networks:
  runner-link: {}
```

Имя `orbstack_tunnel.py` сохранено в коде исторически: это обычный Python TLS-мост,
для Linux используется явный `--bridge-host`, без зависимости от среды разработки.
Доступ к опубликованным портам разрешите только с адреса Runner, включая правила
фильтрации Docker forwarding. Не публикуйте их на общедоступном интерфейсе.
Сертификаты имеют срок действия 30 дней; существующие сертификаты установщик не заменяет.

```sh
docker compose -f compose.yaml -f compose.runner-linux.yaml --profile all config --quiet
docker compose -f compose.yaml -f compose.runner-linux.yaml up -d runner-bridge
```

На узел Runner скопируйте только `ca.crt`, `client.crt`, `client.key` из
`.secrets/runner-tls-client` в `/var/lib/reverse-hr-runner/tls`: владелец runner,
каталог 0700, файлы 0600. Ключ CA и серверный ключ на Runner не передаются.
Установите [unit клиента](reverse-hr-runner-tunnel.service) в `/etc/systemd/system/`
и добавьте `/etc/systemd/system/reverse-hr-runner-tunnel.service.d/linux.conf`:

```ini
[Service]
ExecStart=
ExecStart=/opt/reverse-hr-runner/.venv/bin/python /opt/reverse-hr-runner/infra/runner/orbstack_tunnel.py client --certificates /var/lib/reverse-hr-runner/tls --bridge-host <частный-IP-платформы>
```

Для `reverse-hr-runner.service` добавьте постоянный drop-in:

```ini
[Unit]
Requires=reverse-hr-runner-tunnel.service
After=reverse-hr-runner-tunnel.service
```

В `service.env` БД использует `127.0.0.1:15432`, а API Privacy/Assessment/Workspace/
Evaluation — соответственно `http://127.0.0.1:18001`…`http://127.0.0.1:18004`.
Туннель шифрует и аутентифицирует соединение до выхода с узла; подписи API и
авторизация PostgreSQL продолжают проверяться.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now reverse-hr-runner-tunnel.service
```

После подключения проверьте БД и readiness API, повторите реальные probes,
оформите допуск Assessment, выполните CAS-переключение режима и запустите три
workers по инструкции выше. Проверьте работу refresh timer.

`tests/services/code_runner/test_runner_tunnel.py` проверяет обмен на временных TLS peers,
отказ без сертификата, отказ чужому CA и незакреплённому сертификату, приватные
permissions и запрет ротации. Эти тесты не заменяют проверку соединения на вашем Linux-стенде.
