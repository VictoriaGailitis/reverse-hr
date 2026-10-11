from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class IntegrationConsumer(SignedConsumer):
    service = "integration"

    def __init__(self, engine, signatures, settings):
        super().__init__(engine, signatures, settings)
        from types import SimpleNamespace

        from reverse_hr.protocols.exchange import ExchangeAccess

        access = ExchangeAccess(settings)
        access._signatures = signatures
        self.request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=settings, exchange_access=access))
        )

    def handler(self, event):
        from reverse_hr.services.integration.domain.integration import (
            process_consent_revoked,
            process_deletion_request,
        )

        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return lambda session, message: process_deletion_request(session, message, self.request)
        if event.producer == "privacy" and event.event_type == "privacy.consent_revoked.v1":
            return lambda session, message: process_consent_revoked(session, message, self.request)
        raise InvalidEvent()
