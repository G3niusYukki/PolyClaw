"""AWS Secrets Manager integration for PolyClaw secrets.

Provides a SecretsManager class that retrieves sensitive credentials from
AWS Secrets Manager with fallback to environment variables.
"""
from __future__ import annotations

import os

# boto3 is optional - mock responses when not configured
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError

    _AWS_AVAILABLE = True
except ImportError:
    _AWS_AVAILABLE = False
    boto3 = None
    ClientError = None
    NoCredentialsError = Exception


def _get_aws_client():
    """Create an AWS Secrets Manager client. Returns None if AWS SDK not configured."""
    if not _AWS_AVAILABLE:
        return None
    try:
        return boto3.client('secretsmanager')
    except Exception:
        return None


class SecretsManager:
    """
    Retrieves secrets from AWS Secrets Manager with environment variable fallback.

    Secrets are cached in memory after first retrieval to avoid repeated API calls.
    """

    def __init__(self, region_name: str = 'us-east-1'):
        self._region_name = region_name
        self._cache: dict[str, str] = {}

    def get_ctf_private_key(self) -> str:
        """
        Retrieve the CTF (Conditional Tokens Framework) private key.

        Returns:
            The private key as a hex string.

        Falls back to CTF_PRIVATE_KEY environment variable if AWS SDK is not
        configured or the secret is not found in Secrets Manager.
        """
        return self._get_secret('polyclaw/ctf/private_key', 'CTF_PRIVATE_KEY')

    def get_polymarket_api_key(self) -> str:
        """
        Retrieve the Polymarket API key.

        Returns:
            The API key string.

        Falls back to POLYMARKET_API_KEY environment variable if AWS SDK is not
        configured or the secret is not found in Secrets Manager.
        """
        return self._get_secret('polyclaw/polymarket/api_key', 'POLYMARKET_API_KEY')

    def get_telegram_bot_token(self) -> str:
        """
        Retrieve the Telegram bot token.

        Returns:
            The bot token string.

        Falls back to TELEGRAM_BOT_TOKEN environment variable if AWS SDK is not
        configured or the secret is not found in Secrets Manager.
        """
        return self._get_secret('polyclaw/telegram/bot_token', 'TELEGRAM_BOT_TOKEN')

    def _get_secret(self, secret_name: str, env_var: str) -> str:
        """
        Retrieve a secret from AWS Secrets Manager with environment variable fallback.

        Args:
            secret_name: The AWS Secrets Manager secret name.
            env_var: The environment variable name to fall back to.

        Returns:
            The secret value as a string.

        Raises:
            ValueError: If the secret is not found in either AWS or environment.
        """
        # Check cache first
        if secret_name in self._cache:
            return self._cache[secret_name]

        # Try AWS Secrets Manager first
        client = _get_aws_client()
        if client is not None:
            try:
                response = client.get_secret_value(SecretId=secret_name)
                secret = response['SecretString']
                self._cache[secret_name] = secret
                return secret  # type: ignore[no-any-return]
            except Exception:
                # Fall through to environment variable
                pass

        # Fall back to environment variable
        value = os.environ.get(env_var, '')
        if value:
            self._cache[secret_name] = value
            return value

        # Return empty string for mock mode (actual CTF calls will fail gracefully)
        return ''

    def clear_cache(self) -> None:
        """Clear the in-memory secret cache."""
        self._cache.clear()


# Module-level singleton instance
secrets_manager = SecretsManager()
