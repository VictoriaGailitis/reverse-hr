# Экспериментальный Linux sandbox (BE-06)

NsjailExecutor подключён к opt-in worker execute, выключенному по умолчанию.
Сервис продолжает выдавать technical_error/executor_unavailable. Default
HR_RUNNER_BACKEND=disabled; нет fallback в Python/SQL interpreter хоста, Docker
socket или privileged Compose service. На macOS/ARM64 адаптер запрещает запуск.
Текущий профиль предназначен только для отдельного Linux x86_64 worker/VM.

Реализован обязательный профиль namespaces/RO mounts/seccomp/cgroup v2. Защиты и
формат конфигурации сверены с первичными источниками NsJail:
[config.proto](https://github.com/google/nsjail/blob/master/config.proto),
[supervisor](https://github.com/google/nsjail/blob/master/nsjail.cc),
[cgroup2](https://github.com/google/nsjail/blob/master/cgroup2.cc).
Это проект профиля и адаптер, а не подтверждённая изоляция: Linux probes ещё не
выполнены. Необходимо проверить профиль на конкретном kernel/build NsJail и
подготовленном rootfs, затем отдельно проверить защиту от выхода из sandbox.

Профиль фиксирован сервером: Python 3.12/SQLite demo, вход main.py либо query.sql;
2 CPU секунды, 3 секунды jail wall time, host watchdog 5 секунд; 128 MiB cgroup
memory без swap, address-space 192 MiB; один процесс, не более 32 FD, файл до
1 MiB; tmpfs 8 MiB/128 inodes; общий UTF-8 stdout+stderr до 64 KiB. Эти значения
не принимаются от кандидата. Fork/threads/socket/ptrace/mount/bpf и другие
неразрешённые syscalls завершают процесс; deny-by-default Kafel policy приложена
к исходникам. Namespace NET не имеет активного loopback, /proc не монтируется.
Rootfs и workspace read-only, writable только tmpfs; stdin=/dev/null; env задан
явно, лишние FD закрыты, shell не используется. Пользовательский код/SQL
запускается только через Python внутри подготовленного jail.

SQL demo использует собственную in-memory demo_items таблицу с тремя синтетическими
строками; ATTACH/DETACH/PRAGMA/load_extension запрещены, максимум 20 statements и
100 rows на результат. Это не PostgreSQL runtime и не проверка реального набора
заданий. Hidden tests, калиброванные наборы и оценка ещё не реализованы.

## Подготовка артефактов на отдельном Linux worker

Rootfs.Dockerfile — только шаблон минимального rootfs, без сервисного кода/ключей
платформы. Здесь image не собирался, не скачивался и не экспортировался. Собрать
linux/amd64 образ и извлечь файловую систему следует отдельно, без mounts/API
secrets/socket. Runtime rootfs должен содержать /usr/local/bin/python3.12,
/runner/guest.py (точная копия src/reverse_hr/sandbox_guest.py), /workspace и /tmp.
Бинарник Python/guest не должен быть symlink. NsJail устанавливается отдельно;
адаптер требует SHA-256 его проверенного бинарника, без поиска через PATH.

После проверки состава rootfs создайте manifest вне rootfs:

```sh
PYTHONPATH=src python scripts/runner_inventory.py \
  --rootfs /srv/hr-runtime/rootfs --output /srv/hr-runtime/rootfs-manifest.json
```

Генератор не запускает артефакты и не утверждает их безопасность: review содержимого
предшествует pinning. Не перезаписывает существующий manifest. Адаптер проверяет
SHA-256 manifest, перечень/hash всех обычных файлов и targets symlinks, hash guest,
architecture, executable path, cgroup controllers CPU/memory/pids и cgroup.kill.
Symlinks не разыменовываются в host FS; devices/FIFOs/sockets запрещены. Артефакты
должны быть неизменяемыми для непривилегированных клиентов и обслуживаться
оператором; проверка hash не устраняет race с изменением оператором во время запуска.

Настройки отдельного процесса:
HR_RUNNER_BACKEND=nsjail, HR_RUNNER_NSJAIL_BINARY, HR_RUNNER_NSJAIL_SHA256,
HR_RUNNER_ROOTFS, HR_RUNNER_ROOTFS_MANIFEST, HR_RUNNER_ROOTFS_MANIFEST_SHA256,
HR_RUNNER_CGROUP_PARENT (выделенное delegated cgroup v2 subtree), HR_RUNNER_SCRATCH
(приватный каталог worker). Не указывать root filesystem или общий корень cgroup.
NsJail должен уметь устанавливать обязательные namespaces/cgroups без ослабления
профиля. Никакие новые права/Docker privileged настройки автоматически не выдаются.

## Проверка и очистка

На подготовленном Linux worker выполнить:

```sh
HR_TEST_ENABLE_SANDBOX=1 PYTHONPATH=src python -m pytest tests/test_sandbox_live.py -q
```

Probe fixture требует успешный baseline перед отрицательными проверками. Проверки
включают env, отсутствие /app и host /proc, отказ networking/fork/threads,
memory/file limits, deadline/output flood, cleanup и отдельный SQL demo. Пока они
пропущены. Unit tests с fake process/cgroups проверяют протокол адаптера; проверки
collector с фиксированными trusted host programs не являются тестом sandbox.
Пробелы в syscall policy на нужном runtime не следует обходить DEFAULT ALLOW.

Каждый run использует приватные scratch и собственный свежий cgroup. После
завершения adapter посылает cgroup.kill, ждёт populated=0, удаляет свой subtree и
source/config. Если очистка не подтверждена, Outcome не выдаётся; CleanupUnconfirmed
сохраняет scratch для восстановления. Ошибки supervisor не выдают его логи как
stdout/stderr кандидата. Exit 255 консервативно считается техническим сбоем;
прочие nonzero/signal exits не объявляются автоматически ресурсным лимитом.
Результат исполнения не является score/pass решения, даже при exit 0.

## Журнал попыток и recovery

Migration Code Runner 0003_attempts хранит попытку до создания файлов: UUID попытки,
исходного run, кандидата, стабильного узла, состояние и hash области очистки.
В hash входят абсолютные scratch/cgroup пути, device и inode обоих каталогов.
Смена каталога/монтирования не позволяет другому worker подтвердить очистку старой
области. Потеря узла или смена каталога оставляет обязательство незавершённым;
нужна проверенная оператором процедура восстановления, автоматического ACK нет.

Внутренний reserve_attempt проверяет актуальный signed manifest и резервирует
одну попытку на run транзакционно. execution_scope держит постоянный per-attempt
flock, повторно проверяет состояние, tombstone и исходный manifest, фиксирует active
до возможного запуска. Подготовлен deterministic execute(attempt_id=...); использовать
его можно только внутри execution_scope. Внутренний execute_reserved теперь связывает
этот протокол с приватным результатом; сервисный executor worker пока не подключён.

Recovery получает тот же неблокирующий flock, фиксирует cleaning, выполняет cgroup.kill,
ждёт populated=0 и удаляет временные файлы. Только затем фиксирует cleaned.
Падение до commit оставляет повторяемую очистку; пустые уже очищенные пути допустимы.
Реально работающий worker удерживает lock, поэтому recovery его не опережает.
Запоздалый worker после cleaned или deletion не получает execution_scope.
Время/lease expiry не считается доказательством прекращения процесса.

Privacy deletion сразу блокирует доступ и удаляет jobs/рабочий outbox. Пока есть
хотя бы одна неочищенная попытка на любом узле, отправляется data_restricted.v1.
После последней подтверждённой очистки журнал кандидата удаляется и в той же
транзакции создаётся data_deleted.v1. Оба события version=1, как требует текущий
Privacy ACK контракт; producer/candidate/request/correlation сохраняются.
Постоянный tombstone и технические Inbox/Outbox записи остаются.

На отдельно подготовленном Linux-узле cleanup-only worker можно включить явно:

```sh
HR_SERVICE_NAME=code-runner HR_RUNNER_NODE_ID=<stable-node-uuid> python -m reverse_hr.worker recover
```

Также нужны DB/event-signing настройки и все pins/runtime настройки выше.
HR_RUNNER_SCRATCH должен принадлежать worker и иметь mode 0700, UUID узла должен
сохраняться между рестартами. Lock-файлы остаются вне source scratch и не содержат
кода/результатов: их нельзя unlink при работающих worker из-за inode ABA.
Режим recover закрыт по умолчанию, не включён в Compose и никогда не запускает код.

Следующий этап — проверка Linux isolation, подключение исполнения и hidden tests.
BE-06 ещё не завершён.


## Приватный результат и terminal status

Migration 0004_results хранит один result на run/attempt только после подтверждённой
очистки. Внутренний execute_reserved проверяет signed manifest до выполнения,
получает Outcome, повторяет идемпотентную очистку и проверяет доступ перед записью.
В случае deletion вывод отбрасывается, cleaned/ACK фиксируются без результата.
При отзыве admission пишется cancelled/access_withdrawn с пустым выводом.
Недоступность source или ошибка commit удерживает obligation для recovery.

Status running/version=2 и run_started.v1 создаются до возможного execute. Result,
terminal Job/version=3 и run_finished.v1 (либо run_cancelled.v1) создаются вместе. Эти события содержат
только UUID исходного run/workspace/snapshot/candidate, без stdout/stderr/status/score.
Workspace проецирует running/runner_finished, игнорируя запоздавшие старые версии.
Новые bindings подготовлены configure_events.py, но не применены к брокеру.

GET /code-runner/v1/runs/{run_id}/result доступен владельцу-кандидату с живой
processing/stage admission; чужой/отсутствующий result — 404, закрытый доступ — 409,
недоступный source — 503. JSON содержит исходные snapshot ID/version, UTC completion,
status, exit_code, reason и stdout/stderr. Cache-Control: no-store. Вывод — недоверенный
текст: клиент отображает его как текст, не исполняет HTML/ANSI/код из него.
Combined stdout/stderr ограничен 64 KiB UTF-8, exit_code и сочетания status/reason
валидируются перед записью. Technical failures не содержат supervisor/host diagnostics.
Executed/exit=0 не означает pass решения, grade или успешный hidden test.

Recovery активной попытки после подтверждённой очистки сохраняет technical_error/
executor_interrupted без output и публикует terminal event. Потерянный при crash
вывод не восстанавливается и исходное решение повторно не выполняется. Для reserved
попытки без запуска прежняя диагностика остаётся доступной после cleanup.
Deletion удаляет results немедленно вместе с jobs и рабочими событиями, затем ждёт
оставшиеся sandbox; tombstone не даёт восстановить результат поздним worker.

Opt-in execution worker подключён, но реальное исполнение и Linux probes здесь не включались.
Unit orchestration tests используют doubles для executor и реальные SQLite/flock/
signed admission. Для подключения остаются отдельные Linux/runtime/isolation проверки,
integration/concurrency и реальное прекращение при отмене/отзыве на Linux.


## Отмена владельцем и проверка доступа во время исполнения

Migration 0005_cancellation добавляет durable cancel_requested (default false).
POST /code-runner/v1/runs/{run_id}/cancel требует JWT кандидата-владельца,
Idempotency-Key и If-Match версии Job. Чужой run — 404, устаревшая версия/завершённый
результат — 409. Source admission для остановки не нужна; processing tombstone
проверяется до эффекта и replay. Replay возвращает текущий Job, не старый running.
Если sandbox/obligation ещё нет, Job сразу cancelled/user_cancelled/version=2.
При reserved/active попытке ответ 202 содержит cancel_requested=true; статус остаётся
pending_executor/running до физической очистки. Флаг — монотонный сигнал управления,
сам запрос не увеличивает execution event version. Повторная cancellation не
заменяет уже завершённый результат. Deletion удаляет также cached cancellation replies.

execution_scope не допускает старт отменённой reserved попытки. Recovery после
очистки завершает её run_cancelled.v1/version=2 без ExecutionResult, поскольку
исполнения не было. Для active попытки после cleanup сохраняется пустой cancelled
result и run_cancelled.v1/version=3. Workspace принимает обе версии cancellation,
проецирует runner_cancelled и игнорирует старые/повторные события. Binding подготовлен,
но к существующему RabbitMQ не применён.

Внутренний execute_reserved использует StopMonitor: отдельный поток с паузой 250 ms между проверками
проверяет tombstone/cancel intent и свежую signed source admission. DB transaction
закрывается до удалённого запроса. Getter для collector не делает I/O и не блокирует
watchdog. При отказе — access_withdrawn, при ошибке/проверке старше 1 секунды —
admission_unavailable. Это консервативная политика: медленный источник останавливает
запуск как технический сбой, не нулевая оценка. Отзыв/отмена sticky для данной попытки.
В процессе допускается только один незавершённый monitor; если проверка зависла,
следующие попытки закрыты до её возврата. Exit join ограничен 50 ms, late read не
публикует результат и не выполняет код; detached поток удерживает слот до завершения.

Adapter проверяет stop signal до Popen и во время bounded collector, включая
ситуацию, когда программа закрыла обе трубы, но продолжает работать. Supervisor
останавливается, затем обычный cgroup.kill/cleanup; stdout/stderr отменённой попытки
отбрасываются. Неподтверждённая cleanup сохраняет running/obligation. Перед финальным
commit владелец cancellation проверяется под subject lock, так что поздний Outcome
не превращает отмену в success. При deletion всё равно сохраняется restricted до
cleanup и затем deleted, без приватного результата.

Это протокол в opt-in execution orchestration, по умолчанию выключенном. Unit tests
проверяют реальные local locks/SQLite и trusted фиксированные collector programs;
исходники кандидата на host не запускаются. Фактические NsJail/cgroup остановка,
PostgreSQL гонки cancellation/completion/deletion, runtime compatibility и escapes
остаются непроверенными до возобновления стендовых проверок.


## Opt-in worker исполнения и запись Linux probes

Worker execute теперь соединяет intake/reservation, execution_scope, StopMonitor,
private result и recovery. Каждая итерация сначала проверяет готовность и очищает
одну незавершённую попытку своего узла, затем резервирует новый run. Busy lock или
неподтверждённая cleanup не позволяют перейти к новой попытке; несовпадающий scope
незавершённой попытки этого узла блокирует новые claims. Reserved crash после cleanup
теперь technical_error/executor_interrupted/version2 с run_diagnosed, без result.
Исходное решение никогда автоматически не повторяется, даже если crash был до spawn.

Migration 0006_control хранит singleton mode/version. Первый diagnostic/execute
worker привязывает diagnostic/execution; дальше противоположный режим запрещён.
Diagnostics и execution claim сериализуются через контрольную строку той же БД.
Каждый diagnostic tick и execution claim проверяет mode, поэтому старый процесс
не продолжает диагностировать очередь после её явного переключения.
Operator CLI reverse_hr.runner_control меняет mode по ожидаемой версии только
при отсутствии любых незавершённых cleanup obligations; pending jobs сохраняются.
Это операторская команда с DB credentials, не публичный endpoint кандидата.

Запуск execute требует HR_RUNNER_EXECUTION_ENABLED=true, backend=nsjail, стабильный
HR_RUNNER_NODE_ID, private scratch 0700 и HR_RUNNER_VERIFICATION_FILE. Запись JSON
принадлежит uid worker, mode 0600, regular/non-symlink, без hardlinks, до 32 KiB,
срок <=24 часов и ровно 12 успешных live probes. Fingerprint связывает node,
scratch/cgroup path/device/inode, binary/rootfs pins, kernel/machine, host Python/
версии используемых библиотек, исходники backend/migrations, policy, live tests,
conftest, verifier, pyproject/uv.lock. Изменение среды/кода или истечение срока
закрывает новые claims. Cleanup-only recover не требует этой записи.

Запись создаётся только отдельной командой, которая реально запускает полный
sandbox_live suite в NsJail, без pytest addopts/plugin/deselection overrides. При
любом skipped/failed/error/неполном наборе, timeout или изменении fingerprint запись
не выдаётся. Повторная проверка убирает предыдущую valid-schema запись до probes;
произвольные существующие файлы и symlinks не заменяются. Это локальное свидетельство
перечисленных проверок под доверенным оператором, не криптографический сертификат,
не доказательство отсутствия escapes и не замена отдельной проверки безопасности.
Здесь настоящая запись не создавалась и live suite не запускался.

После provisioning и применения миграций на выделенном Linux/AMD64 worker
(все pins, DB, event signing, source origins и node settings из предыдущих разделов
уже заданы в окружении) подготовлены команды:

```sh
PYTHONPATH=src python scripts/verify_runner.py --output /private/runner/probes.json
PYTHONPATH=src python -m reverse_hr.runner_control execution --if-match-version 1
HR_RUNNER_EXECUTION_ENABLED=true HR_RUNNER_VERIFICATION_FILE=/private/runner/probes.json PYTHONPATH=src python -m reverse_hr.worker execute
```

Для смены mode использовать фактическую control version, не повторять автоматически
пример version1; при outstanding attempts сначала завершить cleanup. Проверки
обновляются до истечения суток; writer выполняется под тем же uid, что worker.
Source origins должны быть доступны по доверенной внутренней сети: Gateway закрывает
internal Workspace/Assessment routes. Не выдавать дополнительный доступ кандидатам.
Обычный Compose остаётся diagnostic, execute service/privileges туда не добавлены.
HR_RUNNER_BACKEND=disabled и HR_RUNNER_EXECUTION_ENABLED=false — defaults.

Unit tests проверяют worker/gates/record writer с synthetic proof и doubles, без
candidate execution на host. 12 Linux probes, runtime compatibility, escapes и
PostgreSQL mode/claim/cleanup races ещё не проверены. Hidden tests, содержательная
оценка и привязка завершения к Assessment/Evaluation остаются впереди.
