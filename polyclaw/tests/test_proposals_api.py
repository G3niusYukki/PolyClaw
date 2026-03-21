from fastapi.testclient import TestClient

from polyclaw.api.main import app


client = TestClient(app)


def test_proposals_endpoint_returns_preview_objects():
    response = client.get('/proposals?limit=3')
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert 'market_id' in data[0]
    assert 'ranking_reasons' in data[0]
    assert 'should_trade' in data[0]
