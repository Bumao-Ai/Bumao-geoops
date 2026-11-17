"""Expiry and rotation tests for the permission policy.

Standard library only: run with

    python -m unittest geoops.tests.test_tokens -v
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest

from geoops.api import PermissionPolicy, PolicyError, hash_token


def utc(offset_seconds: int) -> str:
    """A strict UTC stamp relative to now, so tests do not drift into the past."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset_seconds))


class ExpiryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-tokens-")
        self.path = os.path.join(self.tempdir, "tokens.json")

    def _write(self, rows):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"format": "geoops-tokens", "version": 1, "tokens": rows}, handle)

    def test_expired_token_is_known_but_not_permitted(self) -> None:
        policy = PermissionPolicy()
        policy.grant("expired-token", ["audit:read"], expires_at=utc(-3600))
        self.assertTrue(policy.expired("expired-token"))
        self.assertFalse(policy.known("expired-token"))
        self.assertFalse(policy.permits("expired-token", "audit:read"))
        allowed, reason = policy.check("expired-token", "audit:read")
        self.assertFalse(allowed)
        self.assertEqual(reason, "token expired")

    def test_live_token_still_works(self) -> None:
        policy = PermissionPolicy()
        policy.grant("live-token", ["task:create"], expires_at=utc(3600))
        allowed, reason = policy.check("live-token", "task:create")
        self.assertTrue(allowed)
        self.assertEqual(reason, "ok")
        self.assertFalse(policy.expired("live-token"))

    def test_expiry_before_issue_is_refused(self) -> None:
        policy = PermissionPolicy()
        with self.assertRaises(PolicyError):
            policy.grant(
                "backwards-token",
                ["audit:read"],
                issued_at=utc(600),
                expires_at=utc(60),
            )

    def test_bad_timestamp_format_is_refused(self) -> None:
        policy = PermissionPolicy()
        with self.assertRaises(PolicyError):
            policy.grant("loose-token", ["audit:read"], expires_at="2026-11-16 12:00")

    def test_file_with_expiry_grants_then_expires(self) -> None:
        self._write(
            [
                {
                    "sha256": hash_token("file-token"),
                    "permissions": ["audit:read"],
                    "issued_at": utc(-7200),
                    "expires_at": utc(-60),
                }
            ]
        )
        policy = PermissionPolicy.from_file(self.path)
        self.assertEqual(len(policy), 1)
        allowed, reason = policy.check("file-token", "audit:read")
        self.assertFalse(allowed)
        self.assertEqual(reason, "token expired")

    def test_file_with_bad_expiry_is_refused(self) -> None:
        self._write(
            [
                {
                    "sha256": hash_token("file-token"),
                    "permissions": ["audit:read"],
                    "expires_at": "next week",
                }
            ]
        )
        with self.assertRaises(PolicyError):
            PermissionPolicy.from_file(self.path)

    def test_rotate_replaces_the_old_token(self) -> None:
        policy = PermissionPolicy()
        policy.grant("old-token", ["task:create", "task:transition"])
        policy.rotate("old-token", "new-token")
        self.assertFalse(policy.known("old-token"))
        self.assertTrue(policy.known("new-token"))
        self.assertTrue(policy.permits("new-token", "task:transition"))
        self.assertEqual(policy.permissions("new-token"), ["task:create", "task:transition"])

    def test_rotate_can_narrow_permissions(self) -> None:
        policy = PermissionPolicy()
        policy.grant("old-token", ["task:create", "task:transition"])
        policy.rotate("old-token", "new-token", permissions=["task:create"])
        self.assertEqual(policy.permissions("new-token"), ["task:create"])
        self.assertFalse(policy.permits("new-token", "task:transition"))

    def test_rotate_unknown_token_is_refused(self) -> None:
        policy = PermissionPolicy()
        with self.assertRaises(PolicyError):
            policy.rotate("never-granted", "new-token")

    def test_revoke_makes_the_token_unknown(self) -> None:
        policy = PermissionPolicy()
        policy.grant("doomed-token", ["audit:read"])
        self.assertTrue(policy.revoke("doomed-token"))
        self.assertFalse(policy.known("doomed-token"))
        self.assertFalse(policy.revoke("doomed-token"))


if __name__ == "__main__":
    unittest.main()
