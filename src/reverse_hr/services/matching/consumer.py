from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class MatchingConsumer(SignedConsumer):
    service = "matching"

    def __init__(self, engine, signatures, settings):
        super().__init__(engine, signatures, settings)
        from reverse_hr.protocols.market_access import MarketAccess

        self.access = MarketAccess(settings)
        self.access._signatures = signatures

    def handler(self, event):
        from reverse_hr.services.matching.domain.matching import (
            process_deletion_request,
            process_profile_change,
        )

        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_deletion_request
        if (
            event.producer == "candidate"
            and event.event_type in {"candidate.profile_created.v1", "candidate.profile_updated.v1"}
            or (event.producer == "privacy" and event.event_type == "privacy.consent_revoked.v1")
        ):
            return lambda session, event: process_profile_change(session, event, self.access)
        raise InvalidEvent()
