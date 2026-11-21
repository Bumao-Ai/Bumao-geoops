"""Unit tests for the token file and the audit file.

Standard library only: run with

    python -m unittest geoops.tests.test_audit -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from geoops.api import (
    AuditError,
    AuditLog,
    PermissionPolicy,
    PolicyError,
    hash_token,
)


class TokenFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-audit-test-")
        self.path = os.path.join(self.tempdir, "tokens.json")

    def _write(self, payload):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_file_grants_are_keyed_by_hash(self) -> None:
        self._write(
            {
                "format": "geoops-tokens",
                "version": 1,
                "tokens": [
                    {"sha256": hash_token("secret-token"), "permissions": ["task:create"]}
                ],
            }
        )
        policy = PermissionPolicy.from_file(self.path)
        self.assertFalse(policy.known("wrong-token"))
        self.assertTrue(policy.known("secret-token"))
        self.assertTrue(policy.permits("secret-token", "task:create"))
        self.assertFalse(policy.permits("secret-token", "task:transition"))

    def test_file_with_raw_token_is_refused(self) -> None:
        self._write(
            {
                "format": "geoops-tokens",
                "version": 1,
                "tokens": [{"token": "secret-token", "permissions": ["task:create"]}],
            }
        )
        with self.assertRaises(PolicyError):
            PermissionPolicy.from_file(self.path)

    def test_bad_hash_and_unknown_permission_are_refused(self) -> None:
        self._write(
            {
                "format": "geoops-tokens",
                "version": 1,
                "tokens": [{"sha256": "not-a-hash", "permissions": ["task:create"]}],
            }
        )
        with self.assertRaises(PolicyError):
            PermissionPolicy.from_file(self.path)

        self._write(
            {
                "format": "geoops-tokens",
                "version": 1,
                "tokens": [{"sha256": hash_token("x"), "permissions": ["task:delete"]}],
            }
        )
        with self.assertRaises(PolicyError):
            PermissionPolicy.from_file(self.path)

    def test_duplicate_hash_is_refused(self) -> None:
        same = hash_token("same-token")
        self._write(
            {
                "format": "geoops-tokens",
                "version": 1,
                "tokens": [
                    {"sha256": same, "permissions": ["task:create"]},
                    {"sha256": same, "permissions": ["audit:read"]},
                ],
            }
        )
        with self.assertRaises(PolicyError):
            PermissionPolicy.from_file(self.path)

    def test_granting_the_same_hash_twice_raises(self) -> None:
        policy = PermissionPolicy()
        policy.grant("token-a", ["task:create"])
        with self.assertRaises(PolicyError):
            policy.grant("token-a", ["audit:read"])

    def test_policy_never_stores_the_raw_token(self) -> None:
        policy = PermissionPolicy({"secret-token": ["audit:read"]})
        stored = list(policy._grants.keys())
        self.assertNotIn("secret-token", stored)
        self.assertIn(hash_token("secret-token"), stored)


class AuditFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="geoops-audit-file-")
        self.path = os.path.join(self.tempdir, "audit.jsonl")

    def test_rows_are_appended_and_reloaded(self) -> None:
        log = AuditLog(path=self.path)
        log.record("POST", "/api/v1/tasks", "secret-token", "deny", "missing permission", 403)
        log.record("POST", "/api/v1/tasks", "secret-token", "allow", "created", 201)
        reloaded = AuditLog(path=self.path)
        self.assertEqual(len(reloaded.rows()), 2)
        self.assertEqual(reloaded.denied(), 1)
        first = reloaded.rows()[0]
        self.assertEqual(first["status"], 403)
        self.assertNotEqual(first["token_fp"], "secret-token")
        self.assertEqual(len(first["token_fp"]), 8)

    def test_verify_reports_a_tampered_file_without_raising(self) -> None:
        log = AuditLog(path=self.path)
        log.record("GET", "/api/v1/health", "", "allow", "first", 200)
        self.assertTrue(log.verify()["ok"])
        with open(self.path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        rows[0]["reason"] = "rewritten"
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(rows[0]) + "\n")
        result = log.verify()
        self.assertFalse(result["ok"])
        self.assertIn("hash", result["error"])
        self.assertEqual(result["memory_rows"], 1)

    def test_verify_reports_a_missing_audit_file(self) -> None:
        result = AuditLog(path=self.path).verify()
        self.assertFalse(result["exists"])
        self.assertFalse(result["ok"])
        self.assertIn("missing", result["error"])

    def test_limit_trims_the_oldest_rows(self) -> None:
        log = AuditLog(limit=2, path=self.path)
        for index in range(4):
            log.record("GET", "/api/v1/health", "", "allow", "row %d" % index, 200)
        reloaded = AuditLog(limit=2, path=self.path)
        self.assertEqual(len(reloaded.rows()), 2)
        self.assertEqual(reloaded.rows()[-1]["reason"], "row 3")

    def test_rows_are_hash_chained_and_a_tampered_row_is_refused(self) -> None:
        log = AuditLog(path=self.path)
        log.record("GET", "/api/v1/health", "", "allow", "first", 200)
        log.record("GET", "/api/v1/health", "", "allow", "second", 200)
        reloaded = AuditLog(path=self.path)
        first, second = reloaded.rows()
        self.assertEqual(first["prev_hash"], AuditLog.CHAIN_START)
        self.assertEqual(second["prev_hash"], first["row_hash"])
        self.assertEqual(first["row_hash"], AuditLog.row_digest(first))
        with open(self.path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        rows[0]["status"] = 500
        with open(self.path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        with self.assertRaises(AuditError):
            AuditLog(path=self.path)

    def test_a_legacy_row_without_a_chain_still_loads(self) -> None:
        legacy = {
            "at": "2026-11-16T00:00:00Z", "method": "GET", "path": "/api/v1/health",
            "token_fp": "", "decision": "allow", "reason": "legacy", "status": 200,
        }
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(legacy) + "\n")
        log = AuditLog(path=self.path)
        log.record("GET", "/api/v1/health", "", "allow", "after legacy", 200)
        reloaded = AuditLog(path=self.path)
        first, second = reloaded.rows()
        self.assertEqual(first["reason"], "legacy")
        self.assertEqual(second["prev_hash"], AuditLog.row_digest(first))

    def test_corrupt_line_is_reported_not_dropped(self) -> None:
        log = AuditLog(path=self.path)
        log.record("GET", "/api/v1/health", "", "allow", "ok", 200)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write("{ this is not json\n")
        with self.assertRaises(AuditError):
            AuditLog(path=self.path)

    def test_missing_key_is_reported(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": "2026-11-16T00:00:00Z", "decision": "allow"}) + "\n")
        with self.assertRaises(AuditError):
            AuditLog(path=self.path)


if __name__ == "__main__":
    unittest.main()
