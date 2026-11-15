def test_create_list_delete(client):
    r = client.post("/api/conversations", json={"title": "T1"})
    assert r.status_code == 200
    cid = r.json()["id"]

    r = client.get("/api/conversations")
    assert r.status_code == 200
    assert any(c["id"] == cid for c in r.json())

    r = client.patch(f"/api/conversations/{cid}", json={"title": "T2"})
    assert r.status_code == 200
    assert r.json()["title"] == "T2"

    r = client.delete(f"/api/conversations/{cid}")
    assert r.status_code == 200

    r = client.get(f"/api/conversations/{cid}")
    assert r.status_code == 404
