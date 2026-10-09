# Запросы субъекта данных

`POST /v1/data-subject-requests` принимает `kind=access|correction|restriction`, причину и необязательный domain/purpose. Субъект всегда берётся из токена аутентифицированного пользователя: кандидат, работодатель и проверяющий могут запрашивать собственные данные. Указать другой subject нельзя. Независимый `privacy_officer` с MFA использует `/queue`, `/claim`, `/decision`. Срок — продуктовый параметр `HR_PRIVACY_REQUEST_SLA_DAYS` (30 по умолчанию, 1–365; Compose `PRIVACY_REQUEST_SLA_DAYS`), а не утверждение о законодательном сроке. Due date фиксируется при подаче.

## Ограничение обработки

Restriction действует немедленно при подаче. Domain ограничивает конкретный сервис; отсутствие domain/purpose — все поддержанные сервисы. Purpose ограничивает только соответствующее использование. Исправление и получение собственных данных остаются доступными. Подписанные processing-status, assessment/recording-permission и purpose/contact/company-result-permission проверяют ограничения при использовании. Consent/grant не переписываются. Одобренное ограничение остаётся активным до `/withdraw`; отклонение снимает его. История сохраняется после снятия. Immutable deletion tombstone имеет приоритет.

## Полный архив и страницы

Access принимает любой существующий сервис в `domain` или отсутствие domain для всего платформенного набора. После одобрения:

1. `POST /{request_id}/archives` создаёт архив либо возвращает существующий текущий сбор.
2. `POST /{request_id}/archives/{archive_id}/advance` получает одну подписанную страницу владельца и сохраняет её. Вызывать до `status=ready`. Конкурирующий advance отвечает 409; потерянный ответ не создаёт дубликаты.
3. `GET /{request_id}/archives/{archive_id}` возвращает компактный манифест с capabilities, owners, source digests, page_count, chain_head, digest и подписью Privacy.
4. `GET /{request_id}/archives/{archive_id}/pages` возвращает первую страницу; следующий запрос передаёт непрозрачный `cursor` из `next_cursor`. Последняя страница имеет null cursor.

Каждая запись содержит table/key/data. Большие записи передаются фрагментами: base64 декодируется, части объединяются по table/key и part, затем проверяется SHA256 digest целой записи и разбирается JSON. Исходные PDF и медиа представлены самостоятельными base64 записями по 32 KiB с offset и digest. Их получение не запускает парсер или декодер. File/S3 чтение использует существующую проверку владельца, storage identity, разрешённого object key, размера и хеша; внутренние пути не выдаются.

Каждый owner page подписан и требует свежей permission Privacy. Cursor связан с владельцем, субъектом, запросом, revision, source digest, offset и сроком 15 минут. Архивные download cursors дополнительно связаны с archive ID и signed manifest digest. Ответы скачивания имеют Cache-Control no-store. При каждом скачивании проверяются текущая авторизация запроса, tombstone, подпись манифеста, привязка получателя, цепочка страниц и хеш выданных данных. Изменение source во время сбора даёт 409; готовый архив сохраняет захваченные данные неизменными. Для перезапуска неполного сбора: `POST /{request_id}/archives/{archive_id}/abandon`, затем новый `/archives`. Ready архив нельзя перезаписывать; `/withdraw` отзывает разрешение и удаляет его страницы. Privacy deletion удаляет архивы, историю и чувствительные идемпотентные ответы, включая ответы сотруднику.

Экспортные проекции используют явные таблицы/колонки и ownership joins:

- Candidate: самоописание, контакты, публикация, резюме, импорт и исходные PDF, подтверждённые результаты и предпочтения.
- Assessment/Evaluation: собственные сессии, этапы, задания/подписки/расписания, апелляции, баллы, объяснения человеческой/LLM оценки. Для авторов — собственный контент; для проверяющих — ссылки на собственные действия.
- Coding-workspace/Code-runner: собственные Code/SQL-снимки, запросы запусков и итоговые статусы. Другие решения и скрытые тесты исключены.
- Whiteboard/Media/Proctoring: собственные доски/операции/снимки, записи и проверенные исходные байты, временные линии и решения целостности.
- Employer/Matching: собственные membership, representative facts, апелляции и ссылки на действия; собственная кандидатская проекция, запросы/intent previews и governance действия. Чужие matches не выдаются.
- Hiring: полученные отправленные приглашения/версии, отклики/статусы, собственные сообщения/жалобы/отзывы; автору — свои вакансии, нужды, приглашения и условия. Неотправленные черновики компании не доступны кандидату.
- Achievements/Integration: собственные достижения, связи и история, внешние job/status receipts. Общие импортные batches других аккаунтов исключены.
- Notification/Audit/Privacy: собственные уведомления, предпочтения и проверенные email targets, минимальные delivery outcomes; собственные audit references; consent/grant, запросы, история и метаданные удаления.

Секреты, hidden suites/answers/private rubrics, чужие личности, storage paths, provider credentials, verification codes, nonce/lease/idempotency caches исключены. Недостающая обязательная таблица/колонка даёт 503, а не пустую успешную выгрузку. Пустая корректная таблица означает отсутствие данных.

Identity обслуживается внешним Keycloak. По умолчанию адаптер выключен: capability `external_identity_unavailable`, общий манифест `complete=false`, запрос остаётся approved. При явном подключении read-only адаптера архив включает разрешённую проекцию аккаунта; недоступный включённый источник возвращает 503 и не завершает запрос. Полностью захваченный scoped archive существующего владельца завершает запрос только после подписанных страниц. Архив между сервисами не является единой транзакцией: каждый владелец фиксирует собственный стабильный source digest. Проверка fingerprint повторно сканирует проекцию с ограниченной памятью; при очень больших объёмах количество работы растёт быстрее объёма данных. Автоматический worker не требуется: advance можно продолжать после рестарта API.

Legacy `GET /{request_id}/export` сохраняет прежнюю структуру для четырёх исходных доменов, но явно возвращает `complete=false`, `coverage=legacy_projection` и не завершает запрос. Его пределы 1 MiB/1000 записей сохранены; для больших и полных выгрузок используется архив.

## Исправления

После независимого одобрения `POST /{id}/execute` резервирует applying и отправляет подписанную CAS-команду владельцу. `target`, `source_version`, `proposed_changes` определяют изменяемую декларацию:

- Candidate `profile` (default): полный ProfileUpdate; проверенный грейд не меняется.
- Candidate `contacts`: ContactsCommand, отдельная contacts.version. Связанное резюме синхронизирует контакты и увеличивает свою версию.
- Candidate `resume`: ResumeFields и `source_profile_version`; изменение контактов требует отдельного contacts запроса.
- Candidate `preferences`: CandidatePreferenceCommand с явным confirmed=true и `source_profile_version`; source_version=0 допустим при отсутствии предпочтений.
- Achievements `declared_achievement`: AchievementFields, `target_id`; только self-source со статусом declared. Imported/confirmed evidence неизменно.
- Notification `notification_preferences`: in_app/marketing_in_app с version CAS. Email-адрес и external email preferences изменяются через обычный challenge/consent workflow, generic correction не обходит подтверждение адреса.

Owner receipt идемпотентен по ID запроса и связан с subject/target/ожидаемой новой версией. Потеря ответа не повторяет изменение. Сбой транспорта сохраняет applying; source conflict возвращает in_review, новые данные не перезаписываются. Во время applying отзыв запрещён. Удаление сотрудника сохраняет stable execution key и одобренные изменения; новый независимый сотрудник может claim и повторить запрос к владельцу. Подтверждённые результаты меняются через апелляцию оценки.

## Согласия на внешние уведомления

Аутентифицированные пользователи без candidate роли могут получить policies, предоставить, прочитать и отозвать собственные external_service_notifications/external_marketing_notifications consent. Остальные candidate purposes сохраняют прежнюю роль. Requester notification имеет purpose-permission только для этих двух целей. Обслуживание и маркетинг требуют отдельных согласий.

При явном включении опционального `identity_export_enabled` владелец Identity использует read-only Keycloak adapter. Его проекция включает собственные разрешённые поля аккаунта, явно настроенные attributes и метаданные credentials; пароли, токены и secret data исключены. Только реально полученные подписанные страницы дают capability paged и позволяют завершить архив. Невключённый или недоступный провайдер не подменяется локальным фальшивым аккаунтом.
