from reverse_hr.services.hiring.domain.hiring import HiringBase
from reverse_hr.shared.review_columns import ActionColumns, CaseColumns, PoolColumns


class HiringReviewer(PoolColumns, HiringBase):
    __tablename__ = "hiring_review_pool"


class HiringSLA(CaseColumns, HiringBase):
    __tablename__ = "hiring_review_sla"


class HiringAction(ActionColumns, HiringBase):
    __tablename__ = "hiring_review_actions"
