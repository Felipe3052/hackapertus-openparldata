import pytest
from pydantic import ValidationError

from parltopic.models import ModelDecision


def test_assigned_decision_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="requires at least one evidence ID"):
        ModelDecision(
            status="assigned",
            score=0.9,
            explanation="The affair funds an ERP system.",
            evidence_ids=[],
        )


def test_model_decision_rejects_unknown_fields_and_duplicates() -> None:
    with pytest.raises(ValidationError):
        ModelDecision(
            status="assigned",
            score=0.9,
            explanation="The affair funds an ERP system.",
            evidence_ids=["p1", "p1"],
            extra_field="not allowed",
        )
