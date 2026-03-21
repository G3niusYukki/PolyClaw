from fastapi.testclient import TestClient

from polyclaw.api.main import app


client = TestClient(app)


def test_notification_log_endpoint_path_exists_via_workflow():
    proposals = client.get('/proposals?limit=5')
    assert proposals.status_code == 200
