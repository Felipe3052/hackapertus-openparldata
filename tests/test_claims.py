from pathlib import Path

from parltopic.evaluation.claims import _claims, describe


def test_claims_reference_existing_eval_sets_and_topics():
    claims = _claims()
    assert len({(c.claim_id, c.metric) for c in claims}) == len(claims)
    for claim in claims:
        assert Path(claim.eval_set).exists(), claim.eval_set
        if claim.source.startswith("keyword:"):
            assert Path(claim.source.removeprefix("keyword:")).exists(), claim.source
        else:
            assert claim.source.startswith("results/") and claim.source.endswith(".jsonl")


def test_describe_marks_missing_files():
    report = {"claims": [{"claim_id": "x", "metric": "f1", "stated": 0.5, "value": None,
                          "ok": False}]}
    assert "| x | f1 | 0.5 | missing | **no** |" in describe(report)
