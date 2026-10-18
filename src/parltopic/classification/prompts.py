from parltopic.models import TextSegment, TopicDefinition

SYSTEM_PROMPT = """You classify Swiss parliamentary affairs neutrally by topic.
Use only the supplied passages. Do not judge political positions.
Return JSON with exactly these keys:
status (assigned, not_assigned, uncertain, not_evaluable), score (0 to 1),
explanation (one short sentence), and evidence_ids (a list of passage IDs).
Only cite IDs that appear in the input. A score is a model assessment,
not a calibrated probability."""


def build_user_prompt(topic: TopicDefinition, segments: list[TextSegment]) -> str:
    examples = "\n".join(f"- {item}" for item in topic.positive_examples)
    exclusions = "\n".join(f"- {item}" for item in topic.negative_examples)
    passages = "\n\n".join(f"[{segment.segment_id}] {segment.text}" for segment in segments)
    return f"""TOPIC
Name: {topic.name}
Description: {topic.description}
Synonyms: {', '.join(topic.synonyms)}

POSITIVE EXAMPLES
{examples or '- none'}

NEGATIVE EXAMPLES
{exclusions or '- none'}

PASSAGES
{passages}
"""

