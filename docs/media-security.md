# Media: S3, ClamAV, decoder, backups

Media проверяет весь собранный файл до создания immutable снимка: SHA-256,
структура контейнера, свежая база ClamAV и clean verdict, полный decode FFmpeg.
После сканирования и после decode повторно проверяются Privacy, recording consent
и разрешение текущего этапа. Сбой любой проверки оставляет загрузку незавершённой;
транскрибация и Evaluation такой материал не получают.

## Запуск

Основной `compose.yaml` включает `media-decoder`, `clamav`, `freshclam` и
`privacy-backup-purge` в профиль `all`. ClamAV читает volume сигнатур; отдельный
FreshClam имеет сеть для обновлений. Пустая/устаревшая база означает 503, пока
обновление не завершилось. Media имеет доступ к антивирусу по внутренней сети.
Порты антивируса и декодера на хост не публикуются.

Декодер получает байты через `/run/decoder/decoder.sock`. Его контейнер работает
под непривилегированным пользователем, без сети, секретов, Docker socket,
монтирования Media/DB и доступа к каталогам кандидатов. Root filesystem read-only,
capabilities удалены, `no-new-privileges` включён; лимиты: 512 MiB, 1 CPU, 32 PID,
128 MiB временных файлов. Перед readiness и decode проверяются Linux, read-only
root, capabilities, seccomp, NoNewPrivs, отсутствие сетевых интерфейсов кроме lo,
лимиты cgroup v2 и отсутствие настроек остальных сервисов в окружении.
FFmpeg/ffprobe запускаются через отдельный stdlib launcher с Landlock ABI ≥ 3:
чтение разрешено только runtime directories и одному входному файлу; создание,
запись, truncate, link/rename файлов запрещены, каталог сокета недоступен. Launcher
не использует preexec_fn в многопоточном процессе. Отсутствие Linux Landlock или
блокировка нужных syscalls дают отказ, без запуска незащищённого FFmpeg. Нужны
Landlock-enabled kernel и seccomp profile с разрешёнными landlock_* syscalls.
Это изоляция контейнером с общим ядром хоста, не отдельная виртуальная машина.
[Landlock ABI и truncate](https://docs.kernel.org/userspace-api/landlock.html).

`HR_MEDIA_ANTIVIRUS_REQUIRED=true` и `HR_MEDIA_DECODER_REQUIRED=true` включены
по умолчанию. Локальный запуск без контейнеров допускается только с явным
отключением обоих требований для разработки. Изолированный API самостоятельно
отказывает в обычном host-процессе; его обход отключён в тестах транспорта явно.

О протоколе сканирования: [ClamD INSTREAM](https://docs.clamav.net/manual/Usage/ClamdProtocol.html).
Изоляция сети: [Docker none network](https://docs.docker.com/engine/network/drivers/none/).

## S3

Для S3 предусмотрен `compose.media-s3.yaml`. Нужны отдельно подготовленные
бакеты Media и backups с включённым versioning и всеми четырьмя флагами Block
Public Access. Адаптер проверяет эти настройки при подключении. Не включайте
Object Lock/retention/legal hold, мешающие обязательному удалению; такой запрет
останавливает подтверждение Privacy, а обход governance не используется.

Задайте `MEDIA_S3_BUCKET`, `BACKUP_S3_BUCKET`, при необходимости `S3_REGION`,
`S3_ENDPOINT`, `MEDIA_S3_KMS_KEY_ID`, `BACKUP_S3_KMS_KEY_ID`. AWS endpoint может
оставаться пустым. Пользовательский endpoint требует HTTPS; HTTP допустим только
при явном `HR_S3_ALLOW_INSECURE_LOCAL=true` для localhost/127.0.0.1/::1/minio.

Файлы `.secrets/media-s3.json` и `.secrets/backup-s3.json` должны иметь права 0600
и JSON вида `{"access_key_id":"...","secret_access_key":"..."}`; временные
учётные данные дополнительно содержат `session_token`. Ключи в репозиторий не
добавляются. SDK получает эти данные явно, без ambient credentials и proxy env.
Срок действия временного токена требует перевыпуска файла и перезапуска клиента.

```sh
docker compose -f compose.yaml -f compose.media-s3.yaml --profile all up --build -d
```

Media и Privacy получают отдельные credentials и scope. Разрешения Media:
GetBucketVersioning, GetBucketPublicAccessBlock, ListBucket, ListBucketVersions,
ListBucketMultipartUploads; GetObject/PutObject/DeleteObject/DeleteObjectVersion/
AbortMultipartUpload только под `MEDIA_S3_PREFIX` (по умолчанию `media/`).
Архиву нужны аналогичные права только под `BACKUP_S3_PREFIX` (`backups/`).
Для SSE-KMS добавьте ограниченные права на соответствующий KMS key. Не давайте
доступ к чужим бакетам/prefix или право изменения политик бакета.

Объекты записываются с серверным шифрованием и `If-None-Match: *`; повторная
запись проверяет исходное содержимое. Чтение ограничено размером чанка и SHA-256.
Presigned/public URLs не выдаются. Перед чтением/записью и до/после удаления проверяется marker identity.
Идентификатор закрепляет endpoint/bucket/prefix
и marker хранилища, затем связывается с БД в отдельной startup transaction до
приёма bytes. Rollback загрузки не снимает эту привязку; orphaned writes остаются
в закреплённом scope для удаления. Замена хранилища не позволяет прочитать
или «удалить» старые данные из другого бакета.

Удаление перечисляет все версии, delete markers и незавершённые multipart uploads
в разрешённом scope, удаляет версии по VersionId, abort-ит uploads и проверяет,
что scope пуст. Проверяется `Errors` даже при HTTP 200:
[DeleteObjects](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObjects.html).
Скрытые старые версии ищутся через
[ListObjectVersions / delete markers](https://docs.aws.amazon.com/AmazonS3/latest/userguide/DeleteMarker.html).
Инвентарь ограничен 10 000 объектами/версиями на операцию; превышение требует
операторской очистки и не даёт ложного подтверждения удаления.

Существующие filesystem chunks и legacy DB bytes автоматически в S3 не переносятся.
Для уже заполненной БД требуется отдельный проверенный перенос при остановленных
писателях и сохранении старого хранилища до проверки всех SHA-256. Переключение
настройки само по себе не мигрирует файлы; несовпадение identity даёт 503.

## Резервные копии и Privacy

`backup_archive` хранит общие снимки всех сервисов, включая дампы БД и копии
файлов, с полным списком UUID кандидатов. Для загрузки подготовьте JSON-массив
всех участников снимка. Запускайте команду с настройками живой Privacy DB и
архива, из окружения оператора с разрешением загрузки:

```sh
PYTHONPATH=src .venv/bin/python -m reverse_hr.services.privacy.backup_archive publish \
  --file /absolute/path/snapshot.enc --subjects-file /absolute/path/subjects.json
PYTHONPATH=src .venv/bin/python -m reverse_hr.services.privacy.backup_archive restore-check \
  --snapshot SNAPSHOT_UUID
```

Загрузка сериализуется с блокировкой каждого участника в живом Privacy ledger:
после tombstone новый снимок с этим кандидатом запрещён. Каталог записывается
раньше payload, поэтому прерванная загрузка остаётся видимой для удаления.
Перед восстановлением проверяются каталог, размер, digest и живые tombstones.
`restore-check` — проверка допуска, а не исполнение restore и не долгоживущее
разрешение; фактический restore обязан снова применить живой Privacy fence.
Privacy ledger должен храниться независимо от восстанавливаемых снимков.

Подписанные ACK сервисов сохраняются сразу. Пока зарегистрированный архив не
очищен, `completed_at` остаётся пустым. Worker `purge-backups` использует
DeletionRequest как постоянную очередь и удаляет **весь общий снимок**, если в
нём есть удаляемый кандидат. Сначала удаляются и проверяются payload versions,
потом каталог; это сохраняет возможность повторной попытки после частичного сбоя.
Другие снимки сохраняются. Ошибка записывается как `archive_unavailable`, попытки
повторяются через 30 секунд; в API видны `backup_attempts`, `backup_error`,
`backup_retry_at`. Одна заблокированная задача не мешает другим готовым задачам.

После проверки отсутствия всех копий worker завершает Privacy и создаёт outbox
событие completion. Identity архива закрепляется в БД; отключение настроек,
подмена бакета/prefix или недоступность зарегистрированного архива не дают завершить
удаление. В S3 override требование архива включено явно.

Механизм охватывает копии в зарегистрированном архиве. Полнота списка участников —
обязанность доверенного экспортёра/оператора. Старые внешние snapshots, реплики,
копии за пределами prefix и оставленные локальные файлы нужно инвентаризировать и
перенести под этот механизм либо очищать отдельно. Наличие delete marker не
считается удалением, а шифрование SSE само по себе не является crypto-shredding.

## Проверка

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q tests/services/media/test_media_security.py \
  tests/services/media/test_media_storage_validation.py tests/integration/test_deletion_completion.py
```

Тесты используют stateful S3 transport и настоящий botocore Stubber, проверяют
пагинацию/VersionId/conditional writes, частичное удаление, общие снимки, fresh/stale
сигнатуры, ClamD framing, отказ перед decode, runtime attestation и реальный
FFmpeg через Unix socket. Проверка Unix socket на хосте не подтверждает контейнерную
изоляцию. Live проверка контейнеров, S3/IAM/KMS и настоящего ClamAV выполняется
после настройки окружения; автоматических cloud-изменений эти тесты не делают.
