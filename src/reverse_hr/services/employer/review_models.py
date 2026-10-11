from reverse_hr.services.employer.domain.employer import EmployerBase
from reverse_hr.shared.review_columns import ActionColumns, CaseColumns, PoolColumns


class EmployerReviewer(PoolColumns, EmployerBase):
    __tablename__ = "employer_review_pool"


class EmployerSLA(CaseColumns, EmployerBase):
    __tablename__ = "employer_review_sla"


class EmployerAction(ActionColumns, EmployerBase):
    __tablename__ = "employer_review_actions"
