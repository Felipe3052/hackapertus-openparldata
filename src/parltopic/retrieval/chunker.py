import hashlib
from collections.abc import Iterable

from parltopic.models import Affair, TextSegment


def _segment_id(affair_id: str, field: str, position: int, text: str) -> str:
    identity = f"{affair_id}:{field}:{position}:{text}".encode()
    digest = hashlib.sha1(identity).hexdigest()[:12]
    return f"{affair_id}-{field}-{digest}"


def _chunks(text: str, size: int, overlap: int) -> Iterable[str]:
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start + size // 2:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            yield chunk
        if end == len(text):
            break
        start = max(end - overlap, start + 1)


def chunk_affair(affair: Affair, size: int = 1400, overlap: int = 200) -> list[TextSegment]:
    """Preserve title and document provenance while segmenting longer fields."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")

    segments: list[TextSegment] = []

    def append_field(
        text: str,
        field: str,
        language: str,
        document_id: str | None = None,
        source_url=None,
        split: bool = True,
    ) -> None:
        values = _chunks(text, size, overlap) if split else [text.strip()]
        for value in values:
            if not value:
                continue
            position = len(segments)
            segments.append(
                TextSegment(
                    segment_id=_segment_id(affair.affair_id, field, position, value),
                    affair_id=affair.affair_id,
                    document_id=document_id,
                    text=value,
                    language=language,
                    position=position,
                    source_url=source_url,
                )
            )

    if affair.title.strip():
        append_field(
            affair.title,
            "title",
            affair.language,
            source_url=affair.source_url,
            split=False,
        )
    if affair.text.strip():
        append_field(affair.text, "affair", affair.language, source_url=affair.source_url)
    for document in affair.documents:
        if document.text.strip():
            append_field(
                document.text,
                "document",
                document.language or affair.language,
                document_id=document.document_id,
                source_url=document.source_url,
            )
    return segments
