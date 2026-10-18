import httpx

from parltopic.compiler import CompiledTopic, newest_matches, search_candidates


def test_query_joins_terms_phrases_and_strips_operators():
    compiled = CompiledTopic(
        topic_id="t",
        terms={"de": ["E-Government", "künstliche Intelligenz", "a | b", "E-Government", "!(x)"]},
    )
    # Duplicates collapse, phrases become adjacent words, tsquery operators are removed.
    assert compiled.query("de") == "E-Government | künstliche <-> Intelligenz | a <-> b | x"
    assert compiled.query("fr") == ""


def test_search_stops_on_last_page_even_if_has_more_stays_true():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        calls.append((params["body_key"], params["offset"]))
        offset = int(params["offset"])
        rows = [{"id": i} for i in range(offset, min(offset + 2, 3))]
        return httpx.Response(200, json={"data": rows,
                                         "meta": {"total_records": 3, "has_more": True}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    compiled = CompiledTopic(topic_id="t", terms={"de": ["digital"]})
    found = search_candidates(compiled, languages=["de"], scope="metadata", bodies=["BE"],
                              page_size=2, client=client)
    assert found == {"de": [0, 1, 2]}
    assert calls == [("BE", "0"), ("BE", "2")]


def test_live_ranking_keeps_one_relevant_hit_in_small_pool():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        "data": [{"id": 42, "body_key": "BE", "begin_date": "2026-01-01",
                  "title_de": "ChatGPT in der Verwaltung"}],
    }))) as client:
        results = newest_matches(CompiledTopic(topic_id="fixture", terms={"de": ["ChatGPT"]}),
                                 bodies=["BE"], languages=["de"], client=client)
    assert len(results) == 1
    assert results[0]["score"] > 0
    assert results[0]["matched_terms"] == ["chatgpt"]
