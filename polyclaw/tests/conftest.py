from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from polyclaw.db import Base
from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.registry import StrategyRegistry
from polyclaw.timeutils import utcnow


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the strategy registry before and after each test."""
    StrategyRegistry.reset()
    yield
    StrategyRegistry.reset()


@pytest.fixture(autouse=True)
def reset_signer():
    """Reset the signer singleton before and after each test."""
    from polyclaw.providers import signer
    signer._signer_instance = None
    yield
    signer._signer_instance = None


@pytest.fixture(autouse=True)
def fresh_default_db(tmp_path):
    """Ensure the default test DB has a clean schema with all current columns.

    Uses a fresh temp SQLite file per test session so all new columns
    (is_shadow, strategy_id, status_history, retry_count, etc.) are present.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import polyclaw.db as db_module

    # Use a temp file-based SQLite so it's thread-safe and fresh per test
    tmp_db = tmp_path / 'test.db'
    fresh_engine = create_engine(f'sqlite:///{tmp_db}', future=True)
    FreshSessionLocal = sessionmaker(bind=fresh_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db_module.Base.metadata.create_all(bind=fresh_engine)

    original_engine = db_module.engine
    original_session = db_module.SessionLocal
    db_module.engine = fresh_engine
    db_module.SessionLocal = FreshSessionLocal

    yield

    db_module.engine = original_engine
    db_module.SessionLocal = original_session
    fresh_engine.dispose()


@pytest.fixture
def db_session():
    """Create a fresh in-memory SQLite database for each test.

    Uses an in-memory database to ensure complete isolation between tests.
    Patches db.engine and db.SessionLocal for the duration of the test.
    """
    # Create a fresh in-memory engine for this test
    test_engine = create_engine('sqlite:///:memory:', future=True)
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    # Create all tables in the test database
    Base.metadata.create_all(bind=test_engine)

    # Provide the session
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()



@pytest.fixture
def sample_market():
    """Create a sample market snapshot for testing."""
    now = utcnow()
    return MarketSnapshot(
        market_id='test-market-1',
        title='Will candidate A win the election?',
        description='Test market for unit tests.',
        yes_price=0.55,
        no_price=0.48,
        spread_bps=100,
        liquidity_usd=25000,
        volume_24h_usd=7000,
        category='politics',
        event_key='test-election-2026',
        closes_at=now + timedelta(days=10),
        fetched_at=now,
    )


@pytest.fixture
def low_liquidity_market():
    """Create a low-liquidity market for testing edge cases."""
    now = utcnow()
    return MarketSnapshot(
        market_id='test-market-low-liQ',
        title='Will Jesus Christ return before GTA VI?',
        description='Novelty market.',
        yes_price=0.48,
        no_price=0.52,
        spread_bps=600,
        liquidity_usd=1500,
        volume_24h_usd=200,
        category='novelty',
        event_key='novelty-1',
        closes_at=now + timedelta(days=120),
        fetched_at=now,
    )
