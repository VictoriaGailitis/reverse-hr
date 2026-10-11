from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class NotificationConsumer(SignedConsumer):
    service = "notification"

    def __init__(self, engine, signatures, settings):
        super().__init__(engine, signatures, settings)
        from reverse_hr.protocols.market_access import MarketAccess

        self.access = MarketAccess(settings)
        self.access._signatures = signatures

    def handler(self, event):
        from reverse_hr.services.notification.domain.notification import (
            process_appeal_notice,
            process_company_notice,
            process_deletion_request,
            process_notice,
        )

        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_deletion_request
        if (
            event.producer == "assessment"
            and event.event_type == "assessment.company_notification_requested.v1"
        ):
            return lambda session, event: process_company_notice(session, event, self.access)
        if (
            event.producer == "assessment"
            and event.event_type == "assessment.appeal_notification_requested.v1"
        ):
            return lambda session, event: process_appeal_notice(session, event, self.access)
        if (
            event.producer == "candidate"
            and event.event_type == "candidate.task_notification_requested.v1"
        ):
            from reverse_hr.services.notification.domain.notification import process_task_notice

            return lambda session, event: process_task_notice(session, event, self.access)
        if event.producer == "hiring" and event.event_type == "hiring.notification_requested.v1":
            return lambda session, event: process_notice(session, event, self.access)
        raise InvalidEvent()
