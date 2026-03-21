import uuid


class PaperExecutionProvider:
    def submit_order(self, market, side: str, stake_usd: float, price: float) -> dict:
        quantity = round(stake_usd / max(price, 0.01), 4)
        return {
            'client_order_id': f'paper-{uuid.uuid4().hex[:16]}',
            'venue_order_id': '',
            'status': 'filled',
            'side': side,
            'price': price,
            'size': quantity,
            'notional_usd': stake_usd,
            'mode': 'paper',
        }
