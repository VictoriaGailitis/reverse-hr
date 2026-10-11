"""Service identity is provenance, never an authenticated human reviewer."""

from uuid import UUID

AUTOMATIC_REVIEWER = UUID("a2e5d478-8e21-57f1-a487-5fd87acbbf43")


def human_owners(owners):
    return {str(owner) for owner in owners if owner and str(owner) != str(AUTOMATIC_REVIEWER)}
