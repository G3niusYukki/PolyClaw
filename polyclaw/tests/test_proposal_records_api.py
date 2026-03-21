from fastapi.testclient import TestClient

from polyclaw.api.main import app


client = TestClient(app)


def test_persist_and_status_update_proposal_records():
    persist = client.post('/proposals/persist?limit=5')
    assert persist.status_code == 200
    records = client.get('/proposal-records')
    assert records.status_code == 200
    data = records.json()
    assert isinstance(data, list)
    if not data:
        return
    proposal_id = data[0]['id']
    updated = client.post(f'/proposal-records/{proposal_id}/status?status=reviewed')
    assert updated.status_code == 200
    assert updated.json()['status'] == 'reviewed'
