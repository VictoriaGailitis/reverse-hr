from reverse_hr.platform.settings import SERVICES
from reverse_hr.services.privacy.domain.privacy import (
    process_accepted_invitation,
    process_deletion_ack,
)
from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class PrivacyConsumer(SignedConsumer):
    service = "privacy"

    def handler(self, event):
        if event.producer == "hiring" and event.event_type == "hiring.invitation_accepted.v1":
            return process_accepted_invitation
        if (
            event.producer in SERVICES
            and event.producer != "privacy"
            and (
                event.event_type
                in {f"{event.producer}.data_deleted.v1", f"{event.producer}.data_restricted.v1"}
            )
        ):
            return process_deletion_ack
        raise InvalidEvent()
