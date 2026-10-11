from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class HiringConsumer(SignedConsumer):
    service = "hiring"

    def __init__(self, engine, signatures, settings):
        super().__init__(engine, signatures, settings)
        from reverse_hr.protocols.exchange import ExchangeAccess

        self.exchange = ExchangeAccess(settings)
        self.exchange._signatures = signatures

    def handler(self, event):
        from reverse_hr.services.hiring.domain.hiring import process_deletion_request

        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_deletion_request
        if (
            event.producer == "integration"
            and event.event_type == "integration.ats_status_changed.v1"
        ):
            from reverse_hr.services.hiring.domain.hiring_ats import process_status

            return lambda session, event: process_status(session, event, self.exchange)
        raise InvalidEvent()
