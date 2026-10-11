import argparse
import logging
import time

from reverse_hr.platform.registry import CONSUMER_TYPES, consumer_type
from reverse_hr.platform.settings import Settings
from reverse_hr.shared.db import make_engine
from reverse_hr.shared.event_transport import Signatures, connect, publish_one


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=[
            "publish",
            "consume",
            "diagnose",
            "recover",
            "execute",
            "validate",
            "grade-tests",
            "prepare",
            "collect",
            "evaluate",
            "automatic-evaluate",
            "automatic-grade",
            "recommend-tasks",
            "generate-content",
            "transcribe",
            "purge-backups",
            "company-dispatch",
            "review-sla",
            "audit-retention",
            "notification-delivery",
            "resume-import",
            "achievement-import",
            "integrate",
            "ats-callback",
        ],
    )
    args = parser.parse_args()
    settings = Settings()
    if args.mode in {"prepare", "collect", "evaluate"} and settings.service_name != "evaluation":
        parser.error("Material preparation requires Evaluation")

    if args.mode == "audit-retention" and settings.service_name != "audit":
        parser.error("Audit retention requires Audit")
    delivery_provider = None
    if args.mode == "notification-delivery":
        if settings.service_name != "notification":
            parser.error("External delivery requires Notification")
        from reverse_hr.services.notification.notification_provider import HttpMailProvider

        try:
            delivery_provider = HttpMailProvider(settings)
        except Exception:
            parser.error("External delivery requires an enabled configured HTTPS provider")
    if args.mode == "consume" and settings.service_name not in CONSUMER_TYPES:
        parser.error("Consumer is not implemented for this service")
    if args.mode == "diagnose" and (
        settings.service_name != "code-runner" or settings.runner_execution_enabled
    ):
        parser.error("Diagnostics require Code Runner with execution disabled")
    recovery_executor = None
    if args.mode in {"recover", "execute", "validate", "grade-tests"}:
        if settings.service_name != "code-runner" or settings.runner_node_id is None:
            parser.error("Recovery requires Code Runner and a stable HR_RUNNER_NODE_ID")
        from reverse_hr.services.code_runner.sandbox import NsjailExecutor

        recovery_executor = NsjailExecutor(settings)
        try:
            recovery_executor.cleanup_scope()
            if args.mode in {"execute", "validate", "grade-tests"}:
                from reverse_hr.services.code_runner.runner_readiness import require_execution_ready

                require_execution_ready(recovery_executor)
        except Exception:
            parser.error("Recovery requires a validated, provisioned Linux sandbox")
    model_gateway = None
    if args.mode == "evaluate":
        from reverse_hr.services.evaluation.llm_gateway import ChatCompletionsGateway

        try:
            model_gateway = ChatCompletionsGateway(settings)
        except Exception:
            parser.error(
                "Evaluation requires an enabled, configured LLM gateway and credential file"
            )
    transcription_gateway = None
    if args.mode == "transcribe":
        if settings.service_name != "media":
            parser.error("Transcription requires Media")
        from reverse_hr.services.media.media_transcription import HttpTranscriptionGateway

        try:
            transcription_gateway = HttpTranscriptionGateway(settings)
        except Exception:
            parser.error(
                "Transcription requires an enabled configured HTTPS gateway and credential file"
            )
    if args.mode == "purge-backups" and settings.service_name != "privacy":
        parser.error("Backup cleanup requires Privacy")
    if args.mode == "company-dispatch" and settings.service_name != "assessment":
        parser.error("Company dispatch requires Assessment")
    if args.mode == "review-sla" and settings.service_name not in {
        "hiring",
        "employer",
        "assessment",
    }:
        parser.error("Review SLA requires Hiring, Employer or Assessment")
    if args.mode == "resume-import" and settings.service_name != "candidate":
        parser.error("Resume imports require Candidate")
    expected = {
        "automatic-evaluate": "evaluation",
        "automatic-grade": "assessment",
        "recommend-tasks": "candidate",
        "generate-content": "assessment",
        "achievement-import": "achievements",
        "integrate": "integration",
        "ats-callback": "demo-ats",
    }
    if args.mode in expected and settings.service_name != expected[args.mode]:
        parser.error("Exchange worker mode does not match service")
    generation_gateway = None
    if args.mode == "generate-content":
        from reverse_hr.services.assessment.generation_gateway import GenerationGateway

        try:
            generation_gateway = GenerationGateway(settings)
        except Exception:
            parser.error("Generation requires a configured enabled HTTPS provider and key file")
    signatures = Signatures.from_settings(settings)
    engine = make_engine(settings.database_url.get_secret_value())
    if settings.service_name == "candidate":
        from reverse_hr.services.candidate.domain.candidate_resume import configure

        configure(engine, settings)
    if settings.service_name == "privacy":
        from reverse_hr.services.privacy.backup_archive import configure as configure_backups

        configure_backups(engine, settings)
    if settings.service_name == "media":
        from reverse_hr.services.media.media_storage import configure

        configure(engine, settings)
    if args.mode in {"diagnose", "execute", "validate", "grade-tests"}:
        from sqlalchemy.orm import Session

        from reverse_hr.services.code_runner.domain.code_runner import require_runner_mode

        try:
            with Session(engine) as session, session.begin():
                require_runner_mode(
                    session,
                    "execution"
                    if args.mode in {"execute", "validate", "grade-tests"}
                    else "diagnostic",
                )
        except Exception:
            engine.dispose()
            parser.error("Runner queue mode or migrated database unavailable")
    automation_app = None
    if args.mode in {"automatic-grade", "generate-content", "recommend-tasks"}:
        from types import SimpleNamespace

        from reverse_hr.platform.registry import service_app

        configure = service_app(settings.service_name).configure

        automation_app = SimpleNamespace(
            state=SimpleNamespace(engine=engine, settings=settings),
            include_router=lambda *a, **k: None,
        )
        configure(automation_app, settings, engine)
    # Pika exceptions may contain connection credentials. Only emit bounded error codes.
    logging.disable(logging.CRITICAL)
    connection = None
    try:
        while True:
            try:
                if args.mode in {"automatic-grade", "generate-content", "recommend-tasks"}:
                    from types import SimpleNamespace
                    from uuid import uuid4

                    request = SimpleNamespace(
                        app=automation_app, state=SimpleNamespace(trace_id=uuid4())
                    )
                    if args.mode == "recommend-tasks":
                        from reverse_hr.services.candidate.domain.candidate_recommendations import (
                            run_one,
                        )

                        run_one(request)
                    elif args.mode == "automatic-grade":
                        from reverse_hr.services.assessment.domain.assessment_automatic import (
                            run_one,
                        )

                        run_one(request)
                    else:
                        from reverse_hr.services.assessment.generation_worker import run_one

                        run_one(request, generation_gateway)
                    time.sleep(0.5)
                    continue
                if args.mode == "automatic-evaluate":
                    from reverse_hr.protocols.evaluation_access import MaterialAccess
                    from reverse_hr.protocols.evaluation_artifact_access import ArtifactAccess
                    from reverse_hr.protocols.processing_access import ProcessingAccess
                    from reverse_hr.protocols.proctoring_access import IntegrityAccess
                    from reverse_hr.services.evaluation.evaluation_automatic import run_one

                    material, artifact, processing, integrity = (
                        MaterialAccess(settings),
                        ArtifactAccess(settings),
                        ProcessingAccess(settings),
                        IntegrityAccess(settings),
                    )
                    material._signatures = artifact._signatures = processing._signatures = (
                        signatures
                    )
                    integrity._signatures = signatures
                    run_one(engine, settings, material, artifact, processing, signatures, integrity)
                    time.sleep(0.5)
                    continue
                if args.mode in {"achievement-import", "integrate", "ats-callback"}:
                    from types import SimpleNamespace
                    from uuid import uuid4

                    from reverse_hr.protocols.exchange import ExchangeAccess
                    from reverse_hr.protocols.market_access import MarketAccess
                    from reverse_hr.protocols.processing_access import ProcessingAccess

                    exchange, market, processing = (
                        ExchangeAccess(settings),
                        MarketAccess(settings),
                        ProcessingAccess(settings),
                    )
                    exchange._signatures = market._signatures = processing._signatures = signatures
                    request = SimpleNamespace(
                        app=SimpleNamespace(
                            state=SimpleNamespace(
                                engine=engine,
                                settings=settings,
                                exchange_access=exchange,
                                market_access=market,
                                processing_access=processing,
                            )
                        ),
                        state=SimpleNamespace(trace_id=uuid4()),
                    )
                    if args.mode == "achievement-import":
                        from reverse_hr.services.achievements.domain.achievements import (
                            run_import as perform,
                        )
                    elif args.mode == "integrate":
                        from reverse_hr.services.integration.domain.integration import (
                            run_one as perform,
                        )
                    else:
                        from reverse_hr.services.demo_ats.domain.demo_ats import (
                            run_callback as perform,
                        )
                    if not perform(request):
                        time.sleep(1)
                    continue
                if args.mode == "notification-delivery":
                    from types import SimpleNamespace
                    from uuid import uuid4

                    from reverse_hr.protocols.market_access import MarketAccess
                    from reverse_hr.protocols.processing_access import ProcessingAccess
                    from reverse_hr.services.notification.domain.notification_delivery import (
                        run_one,
                    )

                    processing, market = ProcessingAccess(settings), MarketAccess(settings)
                    processing._signatures = market._signatures = signatures
                    request = SimpleNamespace(
                        app=SimpleNamespace(
                            state=SimpleNamespace(
                                engine=engine,
                                settings=settings,
                                processing_access=processing,
                                market_access=market,
                            )
                        ),
                        state=SimpleNamespace(trace_id=uuid4()),
                    )
                    if not run_one(request, delivery_provider):
                        time.sleep(1)
                    continue
                if args.mode == "resume-import":
                    from reverse_hr.protocols.processing_access import ProcessingAccess
                    from reverse_hr.protocols.resume_access import PDFGuest
                    from reverse_hr.services.candidate.domain.candidate_resume import run_import_one
                    from reverse_hr.shared.media_antivirus import ClamdScanner

                    processing = ProcessingAccess(settings)
                    processing._signatures = signatures
                    scanner = ClamdScanner(settings) if settings.resume_antivirus_required else None
                    if not run_import_one(engine, processing, PDFGuest(settings), scanner):
                        time.sleep(1)
                    continue
                if args.mode == "audit-retention":
                    from reverse_hr.services.audit.domain.audit import run_retention_one

                    if not run_retention_one(engine, settings, signatures=signatures):
                        time.sleep(1)
                    continue
                if args.mode == "review-sla":
                    from types import SimpleNamespace
                    from uuid import uuid4

                    from reverse_hr.coordination.review_sla import run_one as review_sla_one
                    from reverse_hr.protocols.market_access import MarketAccess
                    from reverse_hr.protocols.processing_access import ProcessingAccess

                    processing, market = ProcessingAccess(settings), MarketAccess(settings)
                    processing._signatures = market._signatures = signatures
                    request = SimpleNamespace(
                        app=SimpleNamespace(
                            state=SimpleNamespace(
                                engine=engine,
                                settings=settings,
                                processing_access=processing,
                                market_access=market,
                            )
                        ),
                        state=SimpleNamespace(trace_id=uuid4()),
                    )
                    if not review_sla_one(request):
                        time.sleep(1)
                    continue
                if args.mode == "company-dispatch":
                    from reverse_hr.protocols.grade_access import GradeAccess
                    from reverse_hr.protocols.market_access import MarketAccess
                    from reverse_hr.protocols.processing_access import ProcessingAccess
                    from reverse_hr.services.assessment.company_dispatch import (
                        run_one as dispatch_one,
                    )

                    processing, market, scores = (
                        ProcessingAccess(settings),
                        MarketAccess(settings),
                        GradeAccess(settings),
                    )
                    processing._signatures = market._signatures = scores._signatures = signatures
                    if not dispatch_one(engine, processing, market, scores):
                        time.sleep(1)
                    continue
                if args.mode == "purge-backups":
                    from reverse_hr.services.privacy.backup_archive import (
                        run_one as purge_backups_one,
                    )

                    if not purge_backups_one(engine):
                        time.sleep(3)
                    continue
                if args.mode == "transcribe":
                    from reverse_hr.protocols.processing_access import ProcessingAccess
                    from reverse_hr.protocols.recording_access import RecordingAccess
                    from reverse_hr.protocols.stage_access import StageAccess
                    from reverse_hr.services.media.media_transcription import (
                        run_one as transcribe_one,
                    )

                    processing, recording, stages = (
                        ProcessingAccess(settings),
                        RecordingAccess(settings),
                        StageAccess(settings),
                    )
                    processing._signatures = recording._signatures = stages._signatures = signatures
                    if not transcribe_one(
                        engine, processing, recording, stages, transcription_gateway
                    ):
                        time.sleep(0.5)
                    continue
                if args.mode == "evaluate":
                    from reverse_hr.protocols.evaluation_access import MaterialAccess
                    from reverse_hr.protocols.evaluation_artifact_access import ArtifactAccess
                    from reverse_hr.protocols.processing_access import ProcessingAccess
                    from reverse_hr.services.evaluation.evaluation_llm import (
                        run_one as evaluate_one,
                    )

                    material, artifact, processing = (
                        MaterialAccess(settings),
                        ArtifactAccess(settings),
                        ProcessingAccess(settings),
                    )
                    material._signatures = artifact._signatures = processing._signatures = (
                        signatures
                    )
                    if not evaluate_one(
                        engine,
                        material,
                        artifact,
                        processing,
                        model_gateway,
                        timeout_seconds=settings.evaluation_llm_timeout_seconds,
                    ):
                        time.sleep(0.5)
                    continue
                if args.mode == "collect":
                    from reverse_hr.protocols.evaluation_access import MaterialAccess
                    from reverse_hr.protocols.evaluation_artifact_access import ArtifactAccess
                    from reverse_hr.services.evaluation.evaluation_artifacts import collect_one

                    material_access, artifact_access = (
                        MaterialAccess(settings),
                        ArtifactAccess(settings),
                    )
                    material_access._signatures = artifact_access._signatures = signatures
                    if not collect_one(engine, material_access, artifact_access):
                        time.sleep(0.5)
                    continue
                if args.mode == "prepare":
                    from reverse_hr.protocols.evaluation_access import MaterialAccess
                    from reverse_hr.services.evaluation.evaluation_material import prepare_one

                    access = MaterialAccess(settings)
                    access._signatures = signatures
                    if not prepare_one(engine, access):
                        time.sleep(0.5)
                    continue
                if args.mode == "grade-tests":
                    from reverse_hr.protocols.submitted_access import SubmittedAccess
                    from reverse_hr.services.code_runner.submitted_runner import (
                        run_one as grade_tests,
                    )

                    access = SubmittedAccess(settings)
                    access._signatures = signatures
                    if not grade_tests(engine, access, recovery_executor, signatures):
                        time.sleep(0.5)
                    continue
                if args.mode == "execute":
                    from reverse_hr.protocols.runner_exchange import ManifestAccess
                    from reverse_hr.services.code_runner.runner_lifecycle import run_one

                    access = ManifestAccess(settings)
                    access._signatures = signatures
                    if not run_one(engine, access, recovery_executor):
                        time.sleep(0.5)
                    continue
                if args.mode == "validate":
                    from reverse_hr.protocols.processing_access import ProcessingAccess
                    from reverse_hr.protocols.suite_admission import SuiteAdmissionAccess
                    from reverse_hr.protocols.verdict_delivery import (
                        VerdictDeliveryAccess,
                    )
                    from reverse_hr.services.code_runner.validation_queue import (
                        run_one as validate_one,
                    )

                    processing = ProcessingAccess(settings)
                    admission = SuiteAdmissionAccess(settings)
                    delivery = VerdictDeliveryAccess(settings)
                    processing._signatures = admission._signatures = delivery._signatures = (
                        signatures
                    )
                    if not validate_one(
                        engine, processing, admission, delivery, recovery_executor, signatures
                    ):
                        time.sleep(0.5)
                    continue
                if args.mode == "recover":
                    from reverse_hr.services.code_runner.runner_lifecycle import recover_one
                    from reverse_hr.services.code_runner.submitted_runner import (
                        recover_one as recover_submitted,
                    )
                    from reverse_hr.services.code_runner.validation_lifecycle import (
                        recover_one as recover_validation,
                    )

                    if (
                        not recover_submitted(engine, recovery_executor)
                        and not recover_one(engine, settings.runner_node_id, recovery_executor)
                        and not recover_validation(
                            engine, settings.runner_node_id, recovery_executor
                        )
                    ):
                        time.sleep(0.5)
                    continue
                if args.mode == "diagnose":
                    from reverse_hr.protocols.runner_exchange import ManifestAccess
                    from reverse_hr.services.code_runner.domain.code_runner import diagnose_one

                    access = ManifestAccess(settings)
                    access._signatures = signatures
                    if not diagnose_one(engine, access):
                        time.sleep(0.5)
                    continue
                connection, channel = connect(settings)
                if args.mode == "consume":
                    channel.basic_consume(
                        queue=f"{settings.service_name}.incoming",
                        auto_ack=False,
                        on_message_callback=consumer_type(settings.service_name)(
                            engine, signatures, settings
                        ),
                    )
                    channel.start_consuming()
                else:
                    while connection.is_open and channel.is_open:
                        changed = publish_one(engine, channel, signatures, settings)
                        connection.process_data_events(time_limit=0)
                        if not changed:
                            time.sleep(0.5)
            except KeyboardInterrupt:
                break
            except Exception:
                print(
                    f"worker_unavailable service={settings.service_name} mode={args.mode}",
                    flush=True,
                )
                time.sleep(3)
            finally:
                if connection and connection.is_open:
                    try:
                        connection.close()
                    except Exception:
                        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
