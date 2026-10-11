from reverse_hr.services.employer.domain.employer import (
    process_deletion_request as process_employer_deletion,
)
from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class EmployerConsumer(SignedConsumer):
    service = "employer"

    def handler(self, event):
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_employer_deletion
        raise InvalidEvent()
