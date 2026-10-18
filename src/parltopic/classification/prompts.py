from parltopic.models import TextSegment, TopicDefinition

PROMPT_VERSION = "topic-v2"

SYSTEM_PROMPTS = {
    "topic-v1": """You classify Swiss parliamentary affairs neutrally by topic.
Use only the supplied passages. Do not judge political positions.
Return JSON with exactly these keys:
status (assigned, not_assigned, uncertain, not_evaluable), score (0 to 1),
explanation (one short sentence), and evidence_ids (a list of passage IDs).
Only cite IDs that appear in the input. A score is a model assessment,
not a calibrated probability.""",
    "topic-v2": """You are a deterministic taxonomy annotator for Swiss parliamentary affairs.
Decide whether the affair belongs to the supplied topic. Classify subject matter only; never
judge a political position, party, institution, or proposal.

DECISION POLICY
1. Read the topic definition, inclusions, and exclusions as one operational taxonomy.
2. Return assigned when at least one passage shows that the topic is a substantive object,
   instrument, infrastructure, regulatory concern, implementation method, or material context
   of the affair. The topic need not be the affair's sole or primary policy area.
3. Procurement, financing, governance, supervision, labour rules, consumer rules, reporting,
   security, rights, and public debate count when they concern an included technology or digital
   practice. Do not require the literal words 'digital' or 'Digitalisierung'.
4. A precise title is evidence. Strong technical anchors such as software, ERP, IT systems,
   algorithms, online platforms, electronic communication, data processing, cybersecurity,
   telecom networks, digital media, or remote digital work are sufficient even when the body is
   short. Do not dismiss a named technical system merely because its purpose is not explained.
5. Return not_assigned only when the supplied passages provide affirmative grounds that the
   affair is outside the topic, or contain no included concept after considering synonyms and
   functional equivalents.
6. Return uncertain when there is a plausible topic connection but the available wording is too
   ambiguous to decide. Return not_evaluable only when there is effectively no meaningful text.
7. Before answering, silently test the strongest reason for assigned and the strongest reason
   for not_assigned. Prefer the decision supported by explicit passage evidence.

OUTPUT CONTRACT
Return one JSON object with exactly these keys:
- status: assigned, not_assigned, uncertain, or not_evaluable
- score: a number from 0 to 1 expressing decision strength, not a calibrated probability
- explanation: one concise sentence grounded in the supplied text
- evidence_ids: passage IDs copied exactly from the input

assigned and uncertain require at least one evidence ID. not_assigned may cite the most relevant
passage but must not invent evidence. Only cite IDs present in the input.""",
}


def system_prompt(version: str = PROMPT_VERSION) -> str:
    try:
        return SYSTEM_PROMPTS[version]
    except KeyError as error:
        supported = ", ".join(sorted(SYSTEM_PROMPTS))
        message = f"Unknown prompt version {version!r}; expected one of: {supported}"
        raise ValueError(message) from error


def build_user_prompt(topic: TopicDefinition, segments: list[TextSegment]) -> str:
    examples = "\n".join(f"- {item}" for item in topic.positive_examples)
    exclusions = "\n".join(f"- {item}" for item in topic.negative_examples)
    passages = "\n\n".join(f"[{segment.segment_id}] {segment.text}" for segment in segments)
    return f"""TOPIC TAXONOMY
Name: {topic.name}
Definition and inclusion policy: {topic.description}
Known terms and functional equivalents: {', '.join(topic.synonyms)}

IN-SCOPE EXAMPLES
{examples or '- none supplied'}

OUT-OF-SCOPE EXAMPLES
{exclusions or '- none supplied'}

AFFAIR PASSAGES
{passages}

Apply the decision policy to this affair only and return the JSON object."""
