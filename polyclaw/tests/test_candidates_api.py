from fastapi.testclient import TestClient

from polyclaw.api.main import app


client = TestClient(app)


def test_candidates_endpoint_returns_ranked_markets():
    response = client.get('/candidates?limit=3')
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert 'score' in data[0]
    assert 'reasons' in data[0]
