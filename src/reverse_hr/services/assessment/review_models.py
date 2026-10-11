from reverse_hr.services.assessment.domain.assessment import AssessmentBase
from reverse_hr.shared.review_columns import ActionColumns, CaseColumns, PoolColumns


class AssessmentReviewer(PoolColumns, AssessmentBase):
    __tablename__ = "assessment_review_pool"


class AssessmentSLA(CaseColumns, AssessmentBase):
    __tablename__ = "assessment_review_sla"


class AssessmentAction(ActionColumns, AssessmentBase):
    __tablename__ = "assessment_review_actions"
