import httpx

from parltopic.compiler import CompiledTopic, search_candidates


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
