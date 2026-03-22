from polyclaw.strategies.base import BaseStrategy


class StrategyRegistry:
    """Singleton registry for managing strategy instances."""

    _instance: 'StrategyRegistry | None' = None
    _strategies: dict[str, BaseStrategy]

    def __new__(cls) -> 'StrategyRegistry':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._strategies = {}
        return cls._instance

    def register(self, strategy: BaseStrategy) -> None:
        """Register a strategy instance.

        Args:
            strategy: The strategy instance to register.
        """
        self._strategies[strategy.strategy_id] = strategy

    def get(self, strategy_id: str) -> BaseStrategy | None:
        """Retrieve a registered strategy by ID.

        Args:
            strategy_id: The unique identifier of the strategy.

        Returns:
            The strategy instance, or None if not found.
        """
        return self._strategies.get(strategy_id)

    def list_enabled(self) -> list[BaseStrategy]:
        """List all enabled strategy instances.

        Returns:
            List of enabled strategy instances.
        """
        return [s for s in self._strategies.values() if s.enabled]

    def list_all(self) -> list[BaseStrategy]:
        """List all registered strategy instances.

        Returns:
            List of all strategy instances (enabled and disabled).
        """
        return list(self._strategies.values())

    def clear(self) -> None:
        """Clear all registered strategies. Useful for testing."""
        self._strategies.clear()

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance. Useful for testing."""
        cls._instance = None


# Module-level convenience functions using the singleton.
def register(strategy: BaseStrategy) -> None:
    """Register a strategy with the global registry."""
    StrategyRegistry().register(strategy)


def get_strategy(strategy_id: str) -> BaseStrategy | None:
    """Get a strategy from the global registry by ID."""
    return StrategyRegistry().get(strategy_id)


def list_strategies(enabled_only: bool = False) -> list[BaseStrategy]:
    """List strategies from the global registry.

    Args:
        enabled_only: If True, only return enabled strategies.
    """
    if enabled_only:
        return StrategyRegistry().list_enabled()
    return StrategyRegistry().list_all()


def clear() -> None:
    """Clear all registered strategies from the global registry. Useful for testing."""
    StrategyRegistry().clear()
