import hashlib
import io
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from parltopic.evaluation.claims import _claims, describe, fetch_results


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


def test_archive_digest_and_existing_results_are_protected(tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        content = b'{"affair_id":"fixture"}\n'
        entry = tarfile.TarInfo("results/fixture.jsonl")
        entry.size = len(content)
        archive.addfile(entry, io.BytesIO(content))
    payload = buffer.getvalue()
    digest = hashlib.sha256(payload).hexdigest()

    def download(*args, **kwargs):
        return io.BytesIO(payload)

    with patch("urllib.request.urlopen", side_effect=download):
        with pytest.raises(ValueError, match="SHA256"):
            fetch_results(tmp_path, expected_sha256="wrong")
        assert fetch_results(tmp_path, expected_sha256=digest) == ["results/fixture.jsonl"]
        assert fetch_results(tmp_path, expected_sha256=digest) == ["results/fixture.jsonl"]
        target = tmp_path / "results/fixture.jsonl"
        target.write_text("local user output")
        with pytest.raises(FileExistsError):
            fetch_results(tmp_path, expected_sha256=digest)
        assert target.read_text() == "local user output"
