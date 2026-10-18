import hashlib

from parltopic.models import Affair, TextSegment


def chunk_affair(affair: Affair, size: int = 1400, overlap: int = 200) -> list[TextSegment]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    text = affair.combined_text()
    if not text:
        return []

    segments: list[TextSegment] = []
    start = 0
    position = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start + size // 2:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            identity = f"{affair.affair_id}:{position}:{chunk}".encode()
            digest = hashlib.sha1(identity).hexdigest()[:12]
            segments.append(
                TextSegment(
                    segment_id=f"{affair.affair_id}-{digest}",
                    affair_id=affair.affair_id,
                    text=chunk,
                    language=affair.language,
                    position=position,
                    source_url=affair.source_url,
                )
            )
            position += 1
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return segments

