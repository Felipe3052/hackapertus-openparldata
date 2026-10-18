-- ParlTopic output for OpenParlData (PostgreSQL). Suggestions, never overwrites: a new topic
-- version or a human review adds information, the original suggestion stays.

CREATE TABLE IF NOT EXISTS topics (
    topic_id        text PRIMARY KEY,
    name            text NOT NULL,
    definition      jsonb NOT NULL,          -- the topic YAML (description, terms, examples, policy)
    compiled_query  jsonb,                   -- terms per language written by Apertus, editable
    topic_version   text NOT NULL,           -- sha256 of definition + compiled_query
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS affair_topics (
    affair_id            integer NOT NULL,   -- OpenParlData affairs.id
    topic_id             text NOT NULL REFERENCES topics (topic_id),
    topic_version        text NOT NULL,
    status               text NOT NULL CHECK (status IN
                         ('assigned', 'not_assigned', 'uncertain', 'not_evaluable')),
    explanation          text,
    evidence_text        text,               -- original source text, never model-written
    evidence_document_id text,               -- OpenParlData docs.id when the passage is a document
    evidence_url         text,
    language             text,
    model                text NOT NULL,      -- e.g. swiss-ai/Apertus-v1.5-70B
    prompt_version       text,
    classifier_version   text,
    input_tokens         integer,
    output_tokens        integer,
    created_at           timestamptz NOT NULL DEFAULT now(),
    -- Human in the loop: a reviewer confirms or rejects; the suggestion itself is kept.
    review_decision      text CHECK (review_decision IN ('confirmed', 'rejected')),
    reviewed_by          text,
    reviewed_at          timestamptz,
    PRIMARY KEY (affair_id, topic_id, topic_version)
);

CREATE INDEX IF NOT EXISTS affair_topics_topic_status
    ON affair_topics (topic_id, status) WHERE status IN ('assigned', 'uncertain');

-- Example: confirmed and open suggestions for one topic, newest affairs first.
-- SELECT a.id, a.title_de, t.status, t.review_decision, t.evidence_text
-- FROM affairs a JOIN affair_topics t ON t.affair_id = a.id
-- WHERE t.topic_id = 'digitalisation' AND t.status IN ('assigned', 'uncertain')
-- ORDER BY a.begin_date DESC;
