import pytest
from fastapi.testclient import TestClient

from polyclaw.api.main import app
from polyclaw.safety import CTFLiveCircuitBreaker, _circuit_state

client = TestClient(app)


def test_ctf_circuit_breaker_consecutive_failures():
    """Circuit breaker triggers after N consecutive failures."""
    cb = CTFLiveCircuitBreaker(max_consecutive_send_failures=3)
    cb.record_send_failure()
    assert not _circuit_state.is_global_triggered()
    cb.record_send_failure()
    assert not _circuit_state.is_global_triggered()
    cb.record_send_failure()  # 3rd
    assert _circuit_state.is_global_triggered()


def test_ctf_circuit_breaker_success_resets():
    """Success resets consecutive failure counter so next failure starts from 1."""
    cb = CTFLiveCircuitBreaker(max_consecutive_send_failures=3)
    cb.record_send_failure()  # count = 1
    cb.record_send_failure()  # count = 2
    cb.record_send_success()  # reset count = 0
    cb.record_send_failure()  # count = 1 — circuit still alive
    assert not _circuit_state.is_global_triggered()


def test_ctf_circuit_breaker_rpc_error_sliding_window():
    """RPC error count uses sliding window."""
    cb = CTFLiveCircuitBreaker(max_rpc_errors=3, error_window_seconds=60)
    cb.record_rpc_error()
    cb.record_rpc_error()
    assert not _circuit_state.is_global_triggered()
    cb.record_rpc_error()  # 3rd
    assert _circuit_state.is_global_triggered()


def test_kill_switch_blocks_execution_cycle():
    client.post('/kill-switch/enable', params={'reason': 'test'})
    result = client.post('/execute-ready')
    assert result.status_code == 200
    assert result.json()['orders_submitted'] == 0
    state = client.get('/kill-switch').json()
    assert state['enabled'] is True
    client.post('/kill-switch/disable', params={'reason': 'cleanup'})
