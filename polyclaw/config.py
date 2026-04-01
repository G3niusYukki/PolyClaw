from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'PolyClaw'
    database_url: str = 'sqlite:///./polyclaw.db'
    market_source: str = 'polymarket'
    polymarket_gamma_url: str = 'https://gamma-api.polymarket.com/markets'
    polymarket_positions_url: str = ''
    request_timeout_seconds: int = 20

    execution_mode: str = 'paper'
    require_approval: bool = True
    auto_execute: bool = False
    live_trading_enabled: bool = False
    shadow_mode_enabled: bool = True
    shadow_stage: int = 0
    require_approval_gate: bool = True

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

    # CTF / Polymarket live trading settings
    polygon_rpc_url: str = 'https://polygon-rpc.com'
    ctf_contract_address: str = '0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E'
    ctf_private_key: str = ''
    price_band_pct: float = 2.0
    default_poll_interval: int = 5
    default_poll_timeout: int = 60

    # LLM integration settings
    llm_provider: str = 'openai'  # openai | anthropic
    llm_api_key: str = ''
    llm_model: str = 'gpt-4o'
    llm_max_tokens: int = 2000
    llm_temperature: float = 0.1
    llm_cache_ttl_seconds: int = 3600

    # Future phase toggles
    news_fetcher_enabled: bool = False
    news_max_articles_per_market: int = 5
    news_cache_ttl_minutes: int = 30
    onchain_tracking_enabled: bool = False
    onchain_min_whale_position_usd: float = 1000.0
    onchain_tracked_wallets: str = ''  # comma-separated addresses
    cross_platform_enabled: bool = False
    cross_platform_min_discrepancy_bps: int = 500


settings = Settings()
