import argparse
import logging
import time

from reverse_hr.db import make_engine
from reverse_hr.event_transport import (
    AssessmentConsumer,
    CandidateConsumer,
    EmployerConsumer,
    EvaluationConsumer,
    PrivacyConsumer,
    RunnerConsumer,
    Signatures,
    WorkspaceConsumer,
    connect,
    publish_one,
)
from reverse_hr.settings import Settings


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
        ],
    )
    args = parser.parse_args()
    settings = Settings()
    if args.mode in {"prepare", "collect", "evaluate"} and settings.service_name != "evaluation":
        parser.error("Material preparation requires Evaluation")
    consumers = {
        "privacy": PrivacyConsumer,
        "candidate": CandidateConsumer,
        "employer": EmployerConsumer,
        "assessment": AssessmentConsumer,
        "coding-workspace": WorkspaceConsumer,
        "code-runner": RunnerConsumer,
        "evaluation": EvaluationConsumer,
    }
    if args.mode == "consume" and settings.service_name not in consumers:
        parser.error("Consumer is not implemented for this service")
    if args.mode == "diagnose" and (
        settings.service_name != "code-runner" or settings.runner_execution_enabled
    ):
        parser.error("Diagnostics require Code Runner with execution disabled")
    recovery_executor = None
    if args.mode in {"recover", "execute", "validate", "grade-tests"}:
        if settings.service_name != "code-runner" or settings.runner_node_id is None:
            parser.error("Recovery requires Code Runner and a stable HR_RUNNER_NODE_ID")
        from reverse_hr.sandbox import NsjailExecutor

        recovery_executor = NsjailExecutor(settings)
        try:
            recovery_executor.cleanup_scope()
            if args.mode in {"execute", "validate", "grade-tests"}:
                from reverse_hr.runner_readiness import require_execution_ready

                require_execution_ready(recovery_executor)
        except Exception:
            parser.error("Recovery requires a validated, provisioned Linux sandbox")
    model_gateway = None
    if args.mode == "evaluate":
        from reverse_hr.llm_gateway import ChatCompletionsGateway

        try:
            model_gateway = ChatCompletionsGateway(settings)
        except Exception:
            parser.error(
                "Evaluation requires an enabled, configured LLM gateway and credential file"
            )
    signatures = Signatures.from_settings(settings)
    engine = make_engine(settings.database_url.get_secret_value())
    if args.mode in {"diagnose", "execute", "validate", "grade-tests"}:
        from sqlalchemy.orm import Session

        from reverse_hr.domains.code_runner import require_runner_mode

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
    # Pika exceptions may contain connection credentials. Only emit bounded error codes.
    logging.disable(logging.CRITICAL)
    connection = None
    try:
        while True:
            try:
                if args.mode == "evaluate":
                    from reverse_hr.evaluation_access import MaterialAccess
                    from reverse_hr.evaluation_artifact_access import ArtifactAccess
                    from reverse_hr.evaluation_llm import run_one as evaluate_one
                    from reverse_hr.processing_access import ProcessingAccess

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
                    from reverse_hr.evaluation_access import MaterialAccess
                    from reverse_hr.evaluation_artifact_access import ArtifactAccess
                    from reverse_hr.evaluation_artifacts import collect_one

                    material_access, artifact_access = (
                        MaterialAccess(settings),
                        ArtifactAccess(settings),
                    )
                    material_access._signatures = artifact_access._signatures = signatures
                    if not collect_one(engine, material_access, artifact_access):
                        time.sleep(0.5)
                    continue
                if args.mode == "prepare":
                    from reverse_hr.evaluation_access import MaterialAccess
                    from reverse_hr.evaluation_material import prepare_one

                    access = MaterialAccess(settings)
                    access._signatures = signatures
                    if not prepare_one(engine, access):
                        time.sleep(0.5)
                    continue
                if args.mode == "grade-tests":
                    from reverse_hr.submitted_access import SubmittedAccess
                    from reverse_hr.submitted_runner import run_one as grade_tests

                    access = SubmittedAccess(settings)
                    access._signatures = signatures
                    if not grade_tests(engine, access, recovery_executor, signatures):
                        time.sleep(0.5)
                    continue
                if args.mode == "execute":
                    from reverse_hr.runner_exchange import ManifestAccess
                    from reverse_hr.runner_lifecycle import run_one

                    access = ManifestAccess(settings)
                    access._signatures = signatures
                    if not run_one(engine, access, recovery_executor):
                        time.sleep(0.5)
                    continue
                if args.mode == "validate":
                    from reverse_hr.processing_access import ProcessingAccess
                    from reverse_hr.suite_admission import SuiteAdmissionAccess
                    from reverse_hr.validation_queue import run_one as validate_one
                    from reverse_hr.verdict_delivery import VerdictDeliveryAccess

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
                    from reverse_hr.runner_lifecycle import recover_one
                    from reverse_hr.submitted_runner import recover_one as recover_submitted
                    from reverse_hr.validation_lifecycle import recover_one as recover_validation

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
                    from reverse_hr.domains.code_runner import diagnose_one
                    from reverse_hr.runner_exchange import ManifestAccess

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
                        on_message_callback=consumers[settings.service_name](
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
