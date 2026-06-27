from __future__ import annotations

import json
from typing import Any

from botocore.exceptions import ClientError
from observability import logger


RULES_PREFIX = "rules/"

# recent_usage は「直近いつ利用されたか」を保持できればよく、無制限に伸ばすと
# オブジェクトが肥大化するため、新しい順に一定件数だけ残す。
MAX_USAGE_HISTORY = 20


class S3RuleStore:
    """S3-backed store for reusable review rules.

    Rules are stored one JSON file per rule under
    ``rules/package={frontend|backend}/{rule_id}.json``. ``category`` is kept as
    an in-file attribute (not a partition) so a rule can be re-categorized
    without moving the object.
    """

    def __init__(self, s3_client: Any, bucket: str) -> None:
        """Initialize the rule store.

        Args:
            s3_client: Boto3 S3 client instance.
            bucket: Bucket name such as ``"ai-pr-review-data"``.

        Returns:
            None. Example: ``S3RuleStore(s3_client=s3, bucket="ai-pr-review-data")``.
        """
        self.s3_client = s3_client
        self.bucket = bucket

    def list_rules(self) -> list[dict[str, Any]]:
        """Load all stored rules from S3.

        Returns:
            A list of rule dicts such as
            ``[{"rule_id": "abc", "name": "controller/layer-violation", "package": "backend"}]``.
        """
        logger.debug("listing rules", extra={"prefix": RULES_PREFIX})
        paginator = self.s3_client.get_paginator("list_objects_v2")
        rules: list[dict[str, Any]] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=RULES_PREFIX):
            for content in page.get("Contents", []):
                key = content["Key"]
                if not key.endswith(".json"):
                    continue
                rules.append(self._read_rule(key))
        logger.debug("rules loaded", extra={"count": len(rules)})
        return rules

    def save_rule(self, rule: dict[str, Any]) -> None:
        """Persist a single rule to S3.

        Args:
            rule: Rule dict such as
                ``{"rule_id": "abc", "name": "...", "package": "backend", "body": "..."}``.

        Returns:
            None.
        """
        key = self._rule_key(package=rule["package"], rule_id=rule["rule_id"])
        logger.debug("writing rule to S3", extra={"key": key})
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(rule, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )

    def append_usage(self, rule_id: str, used_at: str) -> None:
        """Append a usage timestamp to an existing rule.

        Unknown ``rule_id`` values are ignored, since a marker may reference a
        rule that was already deleted by the low-usage cleanup.

        Args:
            rule_id: Rule identifier such as ``"abc-123"``.
            used_at: Usage timestamp in ISO 8601 format.

        Returns:
            None.
        """
        key = self._find_rule_key(rule_id)
        if key is None:
            logger.warning(
                "usage marker for unknown rule ignored", extra={"rule_id": rule_id}
            )
            return
        rule = self._read_rule(key)
        usage = list(rule.get("recent_usage") or [])
        usage.append(used_at)
        rule["recent_usage"] = usage[-MAX_USAGE_HISTORY:]
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(rule, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        logger.debug("rule usage appended", extra={"rule_id": rule_id, "key": key})

    def delete_rule(self, rule_id: str, package: str | None = None) -> None:
        """Delete a rule from S3, ignoring unknown ids.

        Args:
            rule_id: Rule identifier such as ``"abc-123"``.
            package: When provided, constructs the S3 key directly without
                scanning. When omitted, falls back to a prefix scan.

        Returns:
            None.
        """
        if package is not None:
            key = self._rule_key(package, rule_id)
        else:
            key = self._find_rule_key(rule_id)
            if key is None:
                logger.warning(
                    "delete for unknown rule ignored", extra={"rule_id": rule_id}
                )
                return
        self.s3_client.delete_object(Bucket=self.bucket, Key=key)
        logger.info("rule deleted", extra={"rule_id": rule_id, "key": key})

    def _rule_key(self, package: str, rule_id: str) -> str:
        return f"{RULES_PREFIX}package={package}/{rule_id}.json"

    def _find_rule_key(self, rule_id: str) -> str | None:
        """Locate the S3 key for a rule id by checking each known package directly."""
        for package in ("frontend", "backend"):
            key = self._rule_key(package, rule_id)
            try:
                self.s3_client.head_object(Bucket=self.bucket, Key=key)
                return key
            except ClientError:
                continue
        return None

    def _read_rule(self, key: str) -> dict[str, Any]:
        body = (
            self.s3_client.get_object(Bucket=self.bucket, Key=key)["Body"]
            .read()
            .decode("utf-8")
        )
        return json.loads(body)
