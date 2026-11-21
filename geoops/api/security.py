"""Write-access policy and audit trail for the HTTP API.

The API never decides who may write by itself: a caller supplies the grants.
A token that is unknown is rejected (401), a token without the required
permission is forbidden (403), and every decision — allow or deny — is written
to an audit trail with a token fingerprint instead of the raw token, so the log
can be shared without leaking a credential.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple


PERMISSIONS = (
    "task:create",
    "task:transition",
    "project:write",
    "dataset:write",
    "catalog:write",
    "deliverable:write",
    "quality:write",
    "review:write",
    "model:invoke",
    "workflow:write",
    "workflow:execute",
    "audit:read",
)
TOKEN_FORMAT = "geoops-tokens"
TOKEN_VERSION = 1
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _parse_time(value: Any, field: str) -> Optional[int]:
    """Parse a strict UTC timestamp; a loose format is refused, not guessed."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise PolicyError("%s must be a UTC string" % field)
    try:
        parsed = time.strptime(value.strip(), _TIME_FMT)
    except ValueError:
        raise PolicyError(
            "%s must look like 2026-11-16T12:00:00Z, got %r" % (field, value)
        )
    return int(calendar.timegm(parsed))


class PolicyError(ValueError):
    """Raised when a token file is malformed; nothing is granted from it."""


def hash_token(token: Any) -> str:
    return hashlib.sha256(str(token or "").strip().encode("utf-8")).hexdigest()


class PermissionPolicy:
    """Map a token hash to a set of permissions.

    Grants are stored as sha256 hashes, so a policy file that leaks does not
    hand out usable tokens. A raw token is hashed on lookup and never kept.
    """

    def __init__(
        self,
        grants: Optional[Dict[str, Iterable[str]]] = None,
        token_hashes: Optional[Dict[str, Iterable[str]]] = None,
    ) -> None:
        self._grants: Dict[str, Dict[str, Any]] = {}
        for token, permissions in (grants or {}).items():
            self.grant(token, permissions)
        for token_hash, permissions in (token_hashes or {}).items():
            self.grant_hash(token_hash, permissions)

    def grant(
        self,
        token: Any,
        permissions: Iterable[str],
        issued_at: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> None:
        token = str(token or "").strip()
        if not token:
            raise PolicyError("token must not be empty")
        self.grant_hash(hash_token(token), permissions, issued_at, expires_at)

    def grant_hash(
        self,
        token_hash: Any,
        permissions: Iterable[str],
        issued_at: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> None:
        token_hash = str(token_hash or "").strip().lower()
        if not _HEX64.match(token_hash):
            raise PolicyError("token hash must be 64 hex characters")
        perms = {str(perm).strip() for perm in permissions}
        unknown = perms.difference(PERMISSIONS)
        if unknown:
            raise PolicyError("unknown permission(s): %s" % ", ".join(sorted(unknown)))
        if token_hash in self._grants:
            raise PolicyError("token hash already granted: %s" % token_hash[:8])
        issued = _parse_time(issued_at, "issued_at")
        expires = _parse_time(expires_at, "expires_at")
        if issued is not None and expires is not None and expires <= issued:
            raise PolicyError("expires_at must be later than issued_at")
        self._grants[token_hash] = {
            "permissions": perms,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "issued_ts": issued,
            "expires_ts": expires,
        }

    # ------------------------------------------------------------- lookups
    def _record(self, token: Any) -> Optional[Dict[str, Any]]:
        token = str(token or "").strip()
        if not token:
            return None
        return self._grants.get(hash_token(token))

    @staticmethod
    def _expired(record: Dict[str, Any], now: Optional[int] = None) -> bool:
        expires = record.get("expires_ts")
        if expires is None:
            return False
        return (int(time.time()) if now is None else now) >= expires

    def expired(self, token: Any) -> bool:
        record = self._record(token)
        return bool(record) and self._expired(record)

    def known(self, token: Any) -> bool:
        record = self._record(token)
        return bool(record) and not self._expired(record)

    def permits(self, token: Any, permission: str) -> bool:
        record = self._record(token)
        if not record or self._expired(record):
            return False
        return permission in record["permissions"]

    def check(self, token: Any, permission: str) -> Tuple[bool, str]:
        """Return (allowed, reason); the reason is what the audit row records."""
        record = self._record(token)
        if not record:
            return False, "unknown token"
        if self._expired(record):
            return False, "token expired"
        if permission not in record["permissions"]:
            return False, "permission %s required" % permission
        return True, "ok"

    def permissions(self, token: Any) -> List[str]:
        record = self._record(token)
        if not record or self._expired(record):
            return []
        return sorted(record["permissions"])

    def revoke(self, token: Any) -> bool:
        """Drop a grant; returns False when the token was never granted."""
        record_hash = hash_token(token)
        return self._grants.pop(record_hash, None) is not None

    def rotate(
        self,
        old_token: Any,
        new_token: Any,
        permissions: Optional[Iterable[str]] = None,
        expires_at: Optional[str] = None,
    ) -> None:
        """Replace one token with another, keeping the permissions unless given."""
        old_record = self._record(old_token)
        if not old_record:
            raise PolicyError("cannot rotate a token that is not granted")
        perms = list(permissions) if permissions is not None else sorted(old_record["permissions"])
        self.grant(new_token, perms, expires_at=expires_at)
        self.revoke(old_token)

    def __len__(self) -> int:
        return len(self._grants)

    @classmethod
    def from_file(cls, path: str) -> "PermissionPolicy":
        """Load grants from a JSON file of sha256 hashes.

        A file that carries a raw ``token`` field is refused: accepting it would
        quietly turn a leakable file into a usable credential store. Optional
        ``issued_at`` and ``expires_at`` must be strict UTC strings; an expired
        entry still loads, it simply stops authorising.
        """
        path = str(path or "").strip()
        if not path:
            raise PolicyError("policy path must not be empty")
        if not os.path.exists(path):
            raise PolicyError("policy file not found: %s" % path)
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise PolicyError("policy file is not valid JSON: %s" % exc)
        if not isinstance(data, dict):
            raise PolicyError("policy file must be a JSON object")
        if data.get("format") != TOKEN_FORMAT:
            raise PolicyError("not a GeoOps token file: format=%r" % data.get("format"))
        if data.get("version") != TOKEN_VERSION:
            raise PolicyError("unsupported token file version: %r" % data.get("version"))
        rows = data.get("tokens")
        if not isinstance(rows, list):
            raise PolicyError("token file has no tokens list")

        token_hashes: Dict[str, Iterable[str]] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise PolicyError("each token entry must be an object")
            if "token" in row:
                raise PolicyError("token files store sha256 hashes, not raw tokens")
            token_hash = row.get("sha256")
            if not isinstance(row.get("permissions"), list):
                raise PolicyError("token entry has no permissions list")
            if token_hash in token_hashes:
                raise PolicyError(
                    "duplicate token hash in file: %s" % str(token_hash)[:8]
                )
            token_hashes[token_hash] = row["permissions"]
        policy = cls()
        for row in rows:
            policy.grant_hash(
                row.get("sha256"),
                row["permissions"],
                issued_at=row.get("issued_at"),
                expires_at=row.get("expires_at"),
            )
        return policy


class AuditError(ValueError):
    """Raised when an audit file is corrupt; rows are not silently dropped."""


class AuditLog:
    """Bounded audit trail, optionally appended to a JSONL file.

    Every row is written with ``flush`` and ``fsync`` so a crash cannot lose the
    last decision silently. Loading refuses a corrupt file instead of dropping
    rows, because a gap in an audit trail is the one thing it must not hide.
    New rows are chained with ``prev_hash``/``row_hash``; a reloaded file whose
    chain does not line up is refused. Rows written before the chain existed
    are still accepted and become the first chained link.
    """

    REQUIRED_KEYS = ("at", "method", "path", "token_fp", "decision", "reason", "status")
    CHAIN_START = "0" * 64

    def __init__(self, limit: int = 200, path: Optional[str] = None) -> None:
        self._rows: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._limit = max(1, int(limit))
        self._path = os.path.abspath(path) if path else None
        self._chain_tip = self.CHAIN_START
        if self._path and os.path.exists(self._path):
            loaded = self._read_file(self._path)
            self._rows = loaded[-self._limit:]
            if loaded:
                last = loaded[-1]
                self._chain_tip = last.get("row_hash") or self.row_digest(last)

    @staticmethod
    def fingerprint(token: Any) -> str:
        token = str(token or "").strip()
        if not token:
            return ""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]

    @staticmethod
    def row_digest(row: Dict[str, Any]) -> str:
        """Hash the decision fields, excluding the chain fields themselves."""
        payload = {
            key: value
            for key, value in row.items()
            if key not in ("prev_hash", "row_hash")
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @property
    def path(self) -> Optional[str]:
        return self._path

    def record(
        self,
        method: str,
        path: str,
        token: Any,
        decision: str,
        reason: str = "",
        status: int = 0,
    ) -> Dict[str, Any]:
        row = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "method": str(method),
            "path": str(path),
            "token_fp": self.fingerprint(token),
            "decision": str(decision),
            "reason": str(reason),
            "status": int(status),
        }
        with self._lock:
            row["prev_hash"] = self._chain_tip
            row["row_hash"] = self.row_digest(row)
            self._rows.append(row)
            self._chain_tip = row["row_hash"]
            if len(self._rows) > self._limit:
                del self._rows[0 : len(self._rows) - self._limit]
            if self._path:
                self._append_file(self._path, row)
        return row

    def rows(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._rows]

    def verify(self) -> Dict[str, Any]:
        """Re-read the audit file and verify its hash chain on demand."""
        with self._lock:
            path = self._path
            memory_rows = len(self._rows)
        if not path:
            return {
                "path": "",
                "exists": False,
                "ok": False,
                "error": "audit log has no file path",
                "memory_rows": memory_rows,
            }
        if not os.path.exists(path):
            return {
                "path": path,
                "exists": False,
                "ok": False,
                "error": "audit file is missing",
                "memory_rows": memory_rows,
            }
        try:
            loaded = self._read_file(path)
        except (AuditError, OSError, UnicodeDecodeError) as exc:
            return {
                "path": path,
                "exists": True,
                "ok": False,
                "error": str(exc),
                "memory_rows": memory_rows,
            }
        last = loaded[-1] if loaded else None
        tip = (
            (last.get("row_hash") or self.row_digest(last))
            if last else self.CHAIN_START
        )
        return {
            "path": path,
            "exists": True,
            "ok": True,
            "rows": len(loaded),
            "memory_rows": memory_rows,
            "chain_tip": tip,
        }

    def denied(self) -> int:
        with self._lock:
            return sum(1 for row in self._rows if row["decision"] == "deny")

    @staticmethod
    def _append_file(path: str, row: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    @classmethod
    def _read_file(cls, path: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        expected = cls.CHAIN_START
        chain_seen = False
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    raise AuditError("audit line %d is not valid JSON" % number)
                if not isinstance(row, dict):
                    raise AuditError("audit line %d is not an object" % number)
                missing = [key for key in cls.REQUIRED_KEYS if key not in row]
                if missing:
                    raise AuditError(
                        "audit line %d is missing: %s" % (number, ", ".join(missing))
                    )
                has_chain = "prev_hash" in row or "row_hash" in row
                if has_chain:
                    if "prev_hash" not in row or "row_hash" not in row:
                        raise AuditError("audit line %d has an incomplete hash chain" % number)
                    if row["prev_hash"] != expected:
                        raise AuditError("audit line %d does not follow the previous row" % number)
                    if row["row_hash"] != cls.row_digest(row):
                        raise AuditError("audit line %d hash does not match its fields" % number)
                    expected = row["row_hash"]
                else:
                    if chain_seen:
                        raise AuditError(
                            "audit line %d is unchained after a chained row" % number
                        )
                    expected = cls.row_digest(row)
                if has_chain:
                    chain_seen = True
                rows.append(row)
        return rows
