from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class ProctoringConsumer(SignedConsumer):
    service = "proctoring"

    def __init__(self, engine, signatures, settings):
        super().__init__(engine, signatures, settings)
        from reverse_hr.protocols.processing_access import ProcessingAccess
        from reverse_hr.protocols.stage_access import StageAccess

        self.processing, self.stages = (ProcessingAccess(settings), StageAccess(settings))
        self.processing._signatures = self.stages._signatures = signatures

    def handler(self, event):
        from reverse_hr.services.proctoring.domain.proctoring import (
            SERVER_KINDS,
            process_environment_event,
        )

        if event.event_type in SERVER_KINDS and event.producer == event.event_type.split(".")[0]:
            return lambda session, event: process_environment_event(
                session, event, self.processing, self.stages
            )
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            from reverse_hr.services.proctoring.domain.proctoring import process_deletion_request

            return process_deletion_request
        raise InvalidEvent()
