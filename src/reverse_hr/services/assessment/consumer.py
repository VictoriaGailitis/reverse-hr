from reverse_hr.services.assessment.domain.assessment_sessions import (
    process_deletion_request as process_assessment_deletion,
)
from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class AssessmentConsumer(SignedConsumer):
    service = "assessment"

    def handler(self, event):
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_assessment_deletion
        raise InvalidEvent()
