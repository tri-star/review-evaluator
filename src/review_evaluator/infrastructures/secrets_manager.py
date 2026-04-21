from __future__ import annotations

import json
from typing import Any


class SecretsManagerStore:
    """Wrapper for AWS Secrets Manager JSON secrets."""

    def __init__(self, client: Any) -> None:
        """Initialize the secret store.

        Args:
            client: Boto3 Secrets Manager client instance.

        Returns:
            None. Example: ``SecretsManagerStore(client=secretsmanager)``.
        """
        self.client = client

    def read_secret_value(self, arn: str | None, key: str) -> str | None:
        """Read a JSON field from Secrets Manager.

        Args:
            arn: Secret ARN such as ``"arn:aws:secretsmanager:ap-northeast-1:123:secret:github-token"``.
            key: JSON field name such as ``"token"``.

        Returns:
            The secret field value such as ``"ghp_example"`` or ``None`` when ARN is empty.
        """
        if not arn:
            return None
        response = self.client.get_secret_value(SecretId=arn)
        secret = json.loads(response["SecretString"])
        return secret.get(key)
