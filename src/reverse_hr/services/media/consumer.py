from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class MediaConsumer(SignedConsumer):
    service = "media"

    def handler(self, event):
        from reverse_hr.services.media.domain.media import process_deletion_request

        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_deletion_request
        raise InvalidEvent()
