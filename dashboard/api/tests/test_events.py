def test_events_chronological(client):
    a = client.post("/api/issues", json={"title": "t", "project": "SYS"}).json()
    client.patch(f"/api/issues/{a['id']}", json={"status": "in_progress"})
    client.post(f"/api/issues/{a['id']}/comment", json={"message": "halfway"})
    events = client.get(f"/api/issues/{a['id']}/events").json()
    assert len(events) >= 3  # created + updated + comment
    timestamps = [e["created_at"] for e in events]
    assert timestamps == sorted(timestamps)
