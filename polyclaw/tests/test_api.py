from fastapi.testclient import TestClient

from polyclaw.api.main import app

client = TestClient(app)


def test_health_and_scan_flow():
    assert client.get('/health').status_code == 200
    scan = client.post('/scan')
    assert scan.status_code == 200
    decisions = client.get('/decisions')
    assert decisions.status_code == 200
    assert isinstance(decisions.json(), list)
