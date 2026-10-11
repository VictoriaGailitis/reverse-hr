from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class RunnerConsumer(SignedConsumer):
    service = "code-runner"

    def __init__(self, engine, signatures, settings):
        super().__init__(engine, signatures, settings)
        from reverse_hr.protocols.runner_exchange import ManifestAccess

        self.access = ManifestAccess(settings)
        self.access._signatures = signatures

    def handler(self, event):
        if (
            event.producer == "assessment"
            and event.event_type == "assessment.generated_validation_requested.v1"
        ):
            from reverse_hr.services.code_runner.generated_validation import receive

            return receive

        from reverse_hr.services.code_runner.domain.code_runner import (
            process_deletion_request,
            process_run_request,
        )

        if (
            event.producer == "coding-workspace"
            and event.event_type == "coding-workspace.run_requested.v1"
        ):
            return lambda session, event: process_run_request(session, event, self.access)
        if event.producer == "assessment" and event.event_type == "assessment.stage_submitted.v1":
            from reverse_hr.services.code_runner.submitted_runner import process_submission

            return lambda session, event: process_submission(session, event, self.access)
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_deletion_request
        raise InvalidEvent()
