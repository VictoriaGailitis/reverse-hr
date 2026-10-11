from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class EvaluationConsumer(SignedConsumer):
    service = "evaluation"

    def __init__(self, engine, signatures, settings):
        super().__init__(engine, signatures, settings)
        from reverse_hr.protocols.processing_access import ProcessingAccess

        self.access = ProcessingAccess(settings)
        self.access._signatures = signatures

    def handler(self, event):
        from reverse_hr.services.evaluation.domain.evaluation import (
            process_deletion_request,
            process_submission,
        )

        if event.producer == "assessment" and event.event_type == "assessment.stage_submitted.v1":
            return lambda session, event: process_submission(session, event, self.access)
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_deletion_request
        raise InvalidEvent()
