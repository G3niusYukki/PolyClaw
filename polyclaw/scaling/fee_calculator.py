"""Fee Calculator — estimates platform fees, gas costs, and total execution cost."""

from dataclasses import dataclass

from polyclaw.execution.orders import OrderSpec


# Platform fee rates (configurable)
FEE_RATE_AMM = 0.00  # 0% for AMM/CLOB venues
FEE_RATE_ORDER_BOOK = 0.01  # 1% for order book

# Polygon gas estimation
POLYGON_GAS_PER_TX = 250_000  # Approximate gas units for a CTF trade
POLYGON_GAS_PRICE_BASE_GWEI = 30.0  # Base fee in gwei
POLYGON_USDC_DECIMALS = 6


@dataclass
class FeeBreakdown:
    """Breakdown of all costs associated with an order."""
    platform_fee: float
    gas_fee: float
    slippage_cost: float
    total_cost: float


class FeeCalculator:
    """
    Calculates the total cost of executing an order.

    Includes:
      - Platform fee (0% for AMM, 1% for order book)
      - Gas fee (estimated Polygon gas cost)
      - Slippage cost (price impact)

    All fees are in USD.
    """

    def __init__(
        self,
        fee_rate_amm: float = FEE_RATE_AMM,
        fee_rate_orderbook: float = FEE_RATE_ORDER_BOOK,
        polygon_gas_price_gwei: float = POLYGON_GAS_PRICE_BASE_GWEI,
        eth_usd_price: float = 3500.0,  # ETH/USD for gas conversion
    ):
        self.fee_rate_amm = fee_rate_amm
        self.fee_rate_orderbook = fee_rate_orderbook
        self.polygon_gas_price_gwei = polygon_gas_price_gwei
        self.eth_usd_price = eth_usd_price

    def calculate_platform_fee(self, order_size_usd: float, venue: str = 'amm') -> float:
        """
        Calculate platform fee for an order.

        Args:
            order_size_usd: Order size in USD
            venue: Execution venue ('amm' or 'orderbook')

        Returns:
            Platform fee in USD
        """
        rate = self.fee_rate_amm if venue == 'amm' else self.fee_rate_orderbook
        return round(order_size_usd * rate, 4)

    def estimate_gas_fee(self, size_usd: float, gas_price_gwei: float | None = None) -> float:
        """
        Estimate Polygon gas fee for a trade.

        Args:
            size_usd: Order size in USD (used to estimate gas units if large)
            gas_price_gwei: Override gas price in gwei

        Returns:
            Estimated gas cost in USD
        """
        gwei = gas_price_gwei or self.polygon_gas_price_gwei

        # Scale gas units slightly for larger trades
        if size_usd > 1000:
            gas_units = POLYGON_GAS_PER_TX * 1.5
        elif size_usd > 500:
            gas_units = POLYGON_GAS_PER_TX * 1.2
        else:
            gas_units = float(POLYGON_GAS_PER_TX)

        # Convert gwei to ETH: (gas_price_gwei * gas_units) / 1e9 = ETH
        gas_eth = (gwei * gas_units) / 1e9
        gas_usd = gas_eth * self.eth_usd_price

        return round(gas_usd, 4)

    def total_cost(
        self,
        order_spec: OrderSpec,
        slippage_pct: float = 0.0,
        venue: str = 'amm',
    ) -> FeeBreakdown:
        """
        Calculate the total cost breakdown for an order.

        Args:
            order_spec: Order specification
            slippage_pct: Expected slippage as a decimal (e.g., 0.01 = 1%)
            venue: Execution venue ('amm' or 'orderbook')

        Returns:
            FeeBreakdown dataclass with all cost components
        """
        notional = order_spec.notional_usd

        platform_fee = self.calculate_platform_fee(notional, venue)
        gas_fee = self.estimate_gas_fee(notional)
        slippage_cost = round(notional * abs(slippage_pct), 4)
        total_cost = round(platform_fee + gas_fee + slippage_cost, 4)

        return FeeBreakdown(
            platform_fee=platform_fee,
            gas_fee=gas_fee,
            slippage_cost=slippage_cost,
            total_cost=total_cost,
        )

    def cost_effective_venue(
        self,
        order_spec: OrderSpec,
        slippage_pct: float = 0.0,
    ) -> str:
        """
        Determine the most cost-effective venue for an order.

        Args:
            order_spec: Order specification
            slippage_pct: Expected slippage as a decimal

        Returns:
            'amm' or 'orderbook' — whichever has lower total cost
        """
        cost_amm = self.total_cost(order_spec, slippage_pct, venue='amm')
        cost_ob = self.total_cost(order_spec, slippage_pct, venue='orderbook')

        if cost_ob.total_cost < cost_amm.total_cost:
            return 'orderbook'
        return 'amm'
