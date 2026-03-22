"""Tests for the PolymarketCTFProvider."""
from unittest.mock import MagicMock, patch

from polyclaw.execution.orders import OrderSpec, OrderType
from polyclaw.providers.signer import WalletSigner


def _mock_order_result(client_order_id: str, side='yes', status='submitted'):
    """Create a mock OrderResult."""
    mock = MagicMock()
    mock.client_order_id = client_order_id
    mock.venue_order_id = f'0x{"a"*64}'
    mock.status = status
    mock.side = side
    mock.price = 0.55
    mock.size = 10.0
    mock.notional_usd = 5.5
    return mock


class TestWalletSigner:
    """Tests for WalletSigner."""

    def test_sign_transaction_with_empty_key(self):
        """Signing without a private key returns a mock signature."""
        signer = WalletSigner(private_key='')
        sig = signer.sign_transaction({'to': '0x123', 'value': 100})
        assert sig.startswith('0x')
        assert len(sig) > 2

    def test_sign_transaction_deterministic(self):
        """The same tx_data should produce the same signature."""
        signer = WalletSigner(private_key='test_key_123')
        tx_data = {'to': '0x456', 'value': 200}
        sig1 = signer.sign_transaction(tx_data)
        sig2 = signer.sign_transaction(tx_data)
        assert sig1 == sig2

    def test_sign_transaction_different_keys(self):
        """Different private keys should produce different signatures."""
        signer1 = WalletSigner(private_key='key1')
        signer2 = WalletSigner(private_key='key2')
        tx_data = {'to': '0x789', 'value': 300}
        sig1 = signer1.sign_transaction(tx_data)
        sig2 = signer2.sign_transaction(tx_data)
        assert sig1 != sig2

    def test_sign_transaction_different_data(self):
        """Different tx_data should produce different signatures."""
        signer = WalletSigner(private_key='same_key')
        sig1 = signer.sign_transaction({'a': 1})
        sig2 = signer.sign_transaction({'a': 2})
        assert sig1 != sig2

    def test_sign_message(self):
        """sign_message should return a hex signature."""
        signer = WalletSigner(private_key='message_key')
        sig = signer.sign_message('Hello PolyClaw')
        assert sig.startswith('0x')
        assert len(sig) > 2

    def test_address_derivation(self):
        """Address should be derived from the private key."""
        signer1 = WalletSigner(private_key='addr_key_1')
        signer2 = WalletSigner(private_key='addr_key_2')
        assert signer1.address != signer2.address
        assert signer1.address.startswith('0x')
        assert len(signer1.address) == 42  # 0x + 40 hex chars

    def test_address_empty_key(self):
        """Empty key should return all-zeros address."""
        signer = WalletSigner(private_key='')
        assert signer.address == '0x' + '0' * 40


class TestPolymarketCTFProvider:
    """Tests for PolymarketCTFProvider."""

    def test_provider_initialization(self):
        """Provider initializes with correct defaults."""
        from polyclaw.providers.ctf import PolymarketCTFProvider

        provider = PolymarketCTFProvider()
        assert provider._rpc_url is not None
        assert provider._contract_address is not None
        assert provider._signer is not None

    def test_provider_custom_rpc_url(self):
        """Provider accepts custom RPC URL."""
        from polyclaw.providers.ctf import PolymarketCTFProvider

        provider = PolymarketCTFProvider(
            rpc_url='https://custom-rpc.example.com',
            contract_address='0xabcdef',
        )
        assert provider._rpc_url == 'https://custom-rpc.example.com'
        assert provider._contract_address == '0xabcdef'

    def test_submit_order_backward_compatible(self):
        """submit_order matches the ExecutionProvider interface signature."""
        from polyclaw.providers.ctf import PolymarketCTFProvider

        provider = PolymarketCTFProvider()
        mock_market = MagicMock()
        mock_market.market_id = 'test-market'
        mock_market.outcome_yes_price = 0.55
        mock_market.outcome_no_price = 0.45

        result_mock = _mock_order_result('test-market-submit')

        with patch.object(provider, '_get_existing_order', return_value=None), \
             patch.object(provider, '_persist_order_result', return_value=result_mock):
            result = provider.submit_order(mock_market, 'yes', 10.0, 0.55)
            assert isinstance(result, dict)
            assert 'client_order_id' in result
            assert 'status' in result

    def test_submit_order_obj_creates_order_result(self):
        """submit_order_obj returns an OrderResult."""
        from polyclaw.providers.ctf import PolymarketCTFProvider

        provider = PolymarketCTFProvider()
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.55,
            size=10.0,
            market_id='test-market',
            outcome='yes',
            client_order_id='test-client-123',
        )

        result_mock = _mock_order_result('test-client-123')

        with patch.object(provider, '_get_existing_order', return_value=None), \
             patch.object(provider, '_persist_order_result', return_value=result_mock):
            result = provider.submit_order_obj(order_spec)
            assert result.client_order_id == 'test-client-123'
            assert result.side == 'yes'
            assert result.price == 0.55
            assert result.size == 10.0
            assert result.notional_usd == 5.5  # 0.55 * 10.0
            assert result.status in ('submitted', 'filled')

    def test_submit_order_idempotency(self):
        """Submitting the same client_order_id twice returns cached result."""
        from polyclaw.providers.ctf import PolymarketCTFProvider

        provider = PolymarketCTFProvider()
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.55,
            size=10.0,
            market_id='test-market',
            outcome='yes',
            client_order_id='idempotent-test-123',
        )
        result_mock = _mock_order_result('idempotent-test-123')
        call_count = 0

        def get_existing(cid):
            nonlocal call_count
            return result_mock if call_count > 0 else None

        def persist(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return result_mock

        with patch.object(provider, '_get_existing_order', side_effect=get_existing), \
             patch.object(provider, '_persist_order_result', side_effect=persist):
            result1 = provider.submit_order_obj(order_spec)
            result2 = provider.submit_order_obj(order_spec)
            assert result1.client_order_id == result2.client_order_id
            assert result1.status == result2.status

    def test_check_fill_returns_order_update(self):
        """check_fill returns an OrderUpdate."""
        from polyclaw.providers.ctf import PolymarketCTFProvider

        provider = PolymarketCTFProvider()
        mock_order = MagicMock()
        mock_order.id = 1
        mock_order.client_order_id = 'test-123'
        mock_order.venue_order_id = ''
        mock_order.status = 'submitted'

        update = provider.check_fill(mock_order)
        assert update.order_id == 1
        assert update.client_order_id == 'test-123'
        assert update.status == 'submitted'

    def test_get_positions_returns_list(self):
        """get_positions returns a list of position dicts."""
        from polyclaw.providers.ctf import PolymarketCTFProvider

        provider = PolymarketCTFProvider()
        positions = provider.get_positions()
        assert isinstance(positions, list)

    def test_get_balances_returns_dict(self):
        """get_balances returns a dict with usdc and eth."""
        from polyclaw.providers.ctf import PolymarketCTFProvider

        provider = PolymarketCTFProvider()
        balances = provider.get_balances()
        assert isinstance(balances, dict)
        assert 'usdc' in balances
        assert 'eth' in balances

    def test_cancel_order_without_venue_id(self):
        """cancel_order returns False when no venue_order_id exists."""
        from polyclaw.providers.ctf import PolymarketCTFProvider

        provider = PolymarketCTFProvider()
        mock_order = MagicMock()
        mock_order.venue_order_id = ''

        result = provider.cancel_order(mock_order)
        assert result is False

    def test_provider_close(self):
        """close() cleans up the HTTP client."""
        from polyclaw.providers.ctf import PolymarketCTFProvider

        provider = PolymarketCTFProvider()
        provider.close()
        assert provider._http_client is None
