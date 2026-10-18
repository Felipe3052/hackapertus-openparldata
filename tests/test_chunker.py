from parltopic.models import Affair, Document
from parltopic.retrieval.chunker import chunk_affair


def test_chunk_affair_preserves_identity_and_language() -> None:
    affair = Affair(affair_id="a-1", title="Digitale Verwaltung", text="E-ID " * 500, language="de")
    segments = chunk_affair(affair, size=300, overlap=50)
    assert len(segments) > 1
    assert all(segment.affair_id == "a-1" for segment in segments)
    assert all(segment.language == "de" for segment in segments)
    assert len({segment.segment_id for segment in segments}) == len(segments)
    assert segments[0].text == "Digitale Verwaltung"


def test_chunk_affair_preserves_document_provenance() -> None:
    affair = Affair(
        affair_id="a-2",
        title="Vorstoss",
        language="fr",
        documents=[
            Document(
                document_id="doc-1",
                text="Portail numérique sécurisé",
                language="fr",
                source_url="https://example.org/doc-1",
            )
        ],
    )
    segments = chunk_affair(affair)
    document_segment = next(segment for segment in segments if segment.document_id == "doc-1")
    assert document_segment.source_url is not None
    assert document_segment.language == "fr"

