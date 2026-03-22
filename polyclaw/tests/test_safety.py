from fastapi.testclient import TestClient

from polyclaw.api.main import app

client = TestClient(app)


def test_kill_switch_blocks_execution_cycle():
    client.post('/kill-switch/enable', params={'reason': 'test'})
    result = client.post('/execute-ready')
    assert result.status_code == 200
    assert result.json()['orders_submitted'] == 0
    state = client.get('/kill-switch').json()
    assert state['enabled'] is True
    client.post('/kill-switch/disable', params={'reason': 'cleanup'})
