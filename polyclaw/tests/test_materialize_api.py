from fastapi.testclient import TestClient

from polyclaw.api.main import app

client = TestClient(app)


def test_materialize_tradable_proposal_creates_decision_when_available():
    proposals = client.get('/proposals?limit=10').json()
    tradable = next((p for p in proposals if p['should_trade']), None)
    if tradable is None:
        return
    response = client.post(f"/proposals/{tradable['market_id']}/materialize")
    assert response.status_code == 200
    payload = response.json()
    assert payload['decisions_created'] == 1
