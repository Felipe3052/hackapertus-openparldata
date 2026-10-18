from parltopic.models import Affair
from parltopic.retrieval.chunker import chunk_affair


def test_chunk_affair_preserves_identity_and_language() -> None:
    affair = Affair(affair_id="a-1", title="Digitale Verwaltung", text="E-ID " * 500, language="de")
    segments = chunk_affair(affair, size=300, overlap=50)
    assert len(segments) > 1
    assert all(segment.affair_id == "a-1" for segment in segments)
    assert all(segment.language == "de" for segment in segments)
    assert len({segment.segment_id for segment in segments}) == len(segments)

