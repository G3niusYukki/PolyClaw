"""Tests for idempotent order submission."""
import uuid
from unittest.mock import MagicMock, patch

from polyclaw.execution.orders import OrderSpec, OrderType
from polyclaw.providers.ctf import PolymarketCTFProvider


def _mock_order(client_order_id: str, status='submitted'):
    """Create a mock Order record."""
    mock = MagicMock()
    mock.client_order_id = client_order_id
    mock.venue_order_id = f'0x{"a"*64}'
    mock.status = status
    mock.side = 'yes'
    mock.price = 0.55
    mock.size = 10.0
    mock.notional_usd = 5.5
    mock.decision_id_fk = None
    return mock


class TestIdempotentOrderSubmission:
    """Tests for idempotent order submission via client_order_id."""

    def setup_method(self):
        """Set up a provider with a mock signer and broadcast for all tests."""
        from unittest.mock import patch
        from polyclaw.providers.signer import WalletSigner
        self.provider = PolymarketCTFProvider()
        # Use a real signer so that _broadcast_signed_tx doesn't fail on address lookup
        self.provider._signer = WalletSigner(private_key='0x' + 'ee' * 32)
        # Also patch _broadcast_signed_tx so tests don't need to mock it individually
        patch.object(self.provider, '_broadcast_signed_tx', return_value='0x' + 'ab' * 32).start()

    def test_duplicate_order_returns_cached_result(self):
        """Submitting an order with the same client_order_id twice returns cached result."""
        provider = self.provider
        client_id = 'unique-idempotent-key-456'
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.55,
            size=10.0,
            market_id='idempotent-market',
            outcome='yes',
            client_order_id=client_id,
        )
        mock_order = _mock_order(client_id)
        call_count = 0

        def get_existing(cid):
            nonlocal call_count
            return mock_order if call_count > 0 else None

        def persist(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_order

        with patch.object(provider, '_get_existing_order', side_effect=get_existing), \
             patch.object(provider, '_persist_order_result', side_effect=persist):
            result1 = provider.submit_order_obj(order_spec)
            assert call_count == 1
            result2 = provider.submit_order_obj(order_spec)
            assert call_count == 1  # Cached, no new persist
            assert result1.client_order_id == result2.client_order_id
            assert result1.status == result2.status

    def test_different_client_order_ids_produce_different_orders(self):
        """Different client_order_ids create separate orders."""
        provider = self.provider
        results = {}
        for client_id in ['order-key-A', 'order-key-B']:
            order_spec = OrderSpec(
                type=OrderType.LIMIT, side='yes', price=0.55, size=10.0,
                market_id='market-1', outcome='yes', client_order_id=client_id,
            )
            mock_order = _mock_order(client_id)
            with patch.object(provider, '_get_existing_order', return_value=None), \
                 patch.object(provider, '_persist_order_result', return_value=mock_order):
                results[client_id] = provider.submit_order_obj(order_spec)

        assert results['order-key-A'].client_order_id != results['order-key-B'].client_order_id

    def test_auto_generated_client_order_id(self):
        """OrderSpec without client_order_id gets auto-generated."""
        provider = self.provider
        order_spec = OrderSpec(
            type=OrderType.LIMIT, side='no', price=0.45, size=5.0,
            market_id='auto-id-market', outcome='no',
        )
        # Use a UUID with exactly 32 hex digits (8-4-4-4-12 format)
        fixed_uuid = uuid.UUID('aaaabbbb-ccccdddd-aaaabbbb-ccccdddd')
        expected_prefix = 'ctf-' + fixed_uuid.hex[:16]
        mock_order = _mock_order(expected_prefix)

        with patch.object(provider, '_get_existing_order', return_value=None), \
             patch.object(provider, '_persist_order_result', return_value=mock_order), \
             patch('polyclaw.providers.ctf.uuid.uuid4', return_value=fixed_uuid):
            result = provider.submit_order_obj(order_spec)
            assert result.client_order_id == expected_prefix

    def test_idempotency_across_order_types(self):
        """Idempotency works for all order types."""
        provider = self.provider
        client_id = 'idempotent-limit-order'
        mock_order = _mock_order(client_id)
        with patch.object(provider, '_get_existing_order', return_value=None), \
             patch.object(provider, '_persist_order_result', return_value=mock_order):
            for order_type in [OrderType.LIMIT, OrderType.IOC, OrderType.POST_ONLY, OrderType.MARKET]:
                order_spec = OrderSpec(
                    type=order_type, side='yes', price=0.55, size=5.0,
                    market_id=f'market-{order_type.value}', outcome='yes',
                    client_order_id=client_id,
                )
                result = provider.submit_order_obj(order_spec)
                assert result.client_order_id == client_id

    def test_backward_compatible_submit_order_is_idempotent(self):
        """The backward-compatible submit_order() is also idempotent."""
        provider = self.provider
        mock_market = MagicMock()
        mock_market.market_id = 'backward-market'
        mock_market.outcome_yes_price = 0.55
        mock_market.outcome_no_price = 0.45

        results = {}
        fixed_uuids = [
            uuid.UUID('aaaabbbb-ccccdddd-aaaabbbb-ccccdddd'),
            uuid.UUID('11112222-33334444-55556666-77778888'),
        ]

        for i in range(2):
            expected_prefix = 'ctf-' + fixed_uuids[i].hex[:16]
            mock_order = _mock_order(expected_prefix)
            with patch.object(provider, '_get_existing_order', return_value=None), \
                 patch.object(provider, '_persist_order_result', return_value=mock_order), \
                 patch('polyclaw.providers.ctf.uuid.uuid4', return_value=fixed_uuids[i]):
                results[i] = provider.submit_order(mock_market, 'yes', 10.0, 0.55)

        assert results[0]['client_order_id'] != results[1]['client_order_id']
        assert set(results[0].keys()) == set(results[1].keys())
