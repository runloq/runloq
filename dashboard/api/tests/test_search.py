def test_search_matches_title(client):
    a = client.post("/api/issues", json={
        "title": "dashboard refactor design", "project": "SYS"
    }).json()
    client.post("/api/issues", json={
        "title": "totally unrelated thing", "project": "SYS"
    })
    r = client.get("/api/search?q=dashboard")
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()]
    assert a["id"] in ids
    assert len(ids) == 1


def test_search_empty_query_400(client):
    r = client.get("/api/search?q=")
    # Pydantic min_length=1 → 422
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# FTS5 edge cases must not return 500
# ---------------------------------------------------------------------------

def test_search_hyphenated_ticket_id_returns_200(client):
    """Hyphenated ticket IDs would crash FTS5; the LIKE fallback must return 200."""
    client.post("/api/issues", json={
        "title": "Test-318 memory leak investigation", "project": "TST"
    })
    r = client.get("/api/search?q=Test-318")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_search_apostrophe_returns_200(client):
    """Apostrophe in query must not cause a 500."""
    r = client.get("/api/search?q=what%27s")
    assert r.status_code == 200


def test_search_colon_returns_200(client):
    """Colon in query (e.g. 'fix: bug') must not cause a 500."""
    r = client.get("/api/search?q=fix%3A+bug")
    assert r.status_code == 200


def test_search_unclosed_quote_returns_200(client):
    """Unclosed double-quote is invalid FTS5 — must not cause a 500."""
    r = client.get('/api/search?q=%22unclosed')
    assert r.status_code == 200


def test_search_leading_or_operator_returns_200(client):
    """Bare OR at the start of a query must not cause a 500."""
    r = client.get("/api/search?q=OR+memory")
    assert r.status_code == 200
