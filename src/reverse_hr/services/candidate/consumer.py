from reverse_hr.services.candidate.domain.candidate import process_deletion_request
from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class CandidateConsumer(SignedConsumer):
    service = "candidate"

    def __init__(self, engine, signatures, settings):
        super().__init__(engine, signatures, settings)
        from reverse_hr.protocols.confirmed_grade_access import ConfirmedGradeAccess

        self.access = ConfirmedGradeAccess(settings)
        self.access._signatures = signatures

    def handler(self, event):
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_deletion_request
        if (
            event.producer == "assessment"
            and event.event_type == "assessment.grade_decision_recorded.v1"
        ):
            from reverse_hr.services.candidate.domain.candidate_grades import process_grade_decision

            return lambda session, event: process_grade_decision(session, event, self.access)
        raise InvalidEvent()
