from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'PolyClaw'
    database_url: str = 'sqlite:///./polyclaw.db'
    market_source: str = 'sample'
    polymarket_gamma_url: str = 'https://gamma-api.polymarket.com/markets'
    request_timeout_seconds: int = 20

    execution_mode: str = 'paper'
    require_approval: bool = True
    auto_execute: bool = False
    live_trading_enabled: bool = False

    max_position_usd: float = 50.0
    max_total_exposure_usd: float = 250.0
    min_confidence: float = 0.62
    min_edge_bps: int = 700
    max_spread_bps: int = 400
    min_liquidity_usd: float = 1000.0
    max_market_age_minutes: int = 180
    scan_limit: int = 20
    max_daily_loss_usd: float = 200.0
    max_consecutive_failures: int = 3


settings = Settings()
