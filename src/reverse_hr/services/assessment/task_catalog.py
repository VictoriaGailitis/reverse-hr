"""Bounded signed public catalog: no task answers, tests or company-private content."""

import json

from fastapi import APIRouter, Request
from sqlalchemy import select

from reverse_hr.contracts.market_contracts import MarketRequest
from reverse_hr.protocols.market_access import Signature, respond
from reverse_hr.services.assessment.domain.assessment_evaluation import MaterialNonce
from reverse_hr.services.assessment.domain.assessment_generation import (
    GenerationJob,
    GenerationReference,
)

router = APIRouter(prefix="/internal/v1/market")


@router.post("/task-catalog")
def catalog(request: Request, body: MarketRequest, signature: Signature = None):
    def check(session):
        query = select(GenerationReference).where(
            GenerationReference.organization_id.is_(None),
            GenerationReference.status == "published",
            GenerationReference.version_id.in_(
                select(GenerationJob.version_id).where(GenerationJob.status == "ready")
            ),
        )
        if body.catalog_after:
            query = query.where(GenerationReference.version_id > str(body.catalog_after))
        if body.catalog_version_id:
            query = query.where(GenerationReference.version_id == str(body.catalog_version_id))
        rows = list(session.scalars(query.order_by(GenerationReference.version_id).limit(4)))
        items = [
            dict(
                version_id=row.version_id,
                name=row.data["name"],
                specialization=row.data["specialization"],
                grade=row.data["grade"],
                stack_tags=row.data.get("stack_tags", []),
                format=row.data["format"],
            )
            for row in rows[:3]
        ]
        # Reserve room for the signed envelope and escaped Unicode metadata.
        while len(json.dumps(items, ensure_ascii=True).encode()) > 11000 and len(items) > 1:
            items.pop()
        return dict(
            items=items, next_cursor=items[-1]["version_id"] if len(rows) > len(items) else None
        ), 1

    return respond(
        request, body, signature, "assessment", "task-catalog", MaterialNonce, {"candidate"}, check
    )
