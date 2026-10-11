from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class WhiteboardConsumer(SignedConsumer):
    service = "whiteboard"

    def handler(self, event):
        from reverse_hr.services.whiteboard.domain.whiteboard import process_deletion_request

        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_deletion_request
        raise InvalidEvent()
