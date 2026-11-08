"""Host rules database for Bumao GeoOps.

No rule pack exists yet. The module satisfies the kernel's host contract with
zero rules: an empty rule directory plus the ``zero_rules`` flag lets the
kernel's A1 reconciliation resolve without inventing rules.

No ``check_drift`` and no ``daiban`` member is supplied on purpose. The kernel
reports "cannot compute" instead of receiving a fabricated zero.
"""

import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = PROJECT_ROOT
ROOT = PROJECT_ROOT
RULES_DIR = os.path.join(PROJECT_ROOT, "geoops", "rules")
META_PATH = os.path.join(PROJECT_ROOT, "geoops", "meta.json")


def load_meta():
    with open(META_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def load():
    return {"meta": load_meta(), "chapters": [], "clauses": []}


def index(db):
    meta = dict(db.get("meta") or load_meta())
    clauses = list(db.get("clauses") or [])
    chapters = list(db.get("chapters") or [])
    return {"meta": meta, "clauses": clauses, "chapters": chapters}


def dup_ids(db):
    seen = set()
    duplicates = []
    for clause in db.get("clauses") or []:
        clause_id = clause.get("id")
        if clause_id in seen:
            duplicates.append(clause_id)
        seen.add(clause_id)
    return duplicates


def block_broken(clauses):
    roots = []
    broken = []
    for clause in clauses or []:
        root = str(clause.get("id") or "").split("(")[0]
        if not roots or roots[-1] != root:
            if root in roots:
                broken.append(root)
            roots.append(root)
    return broken


def shell_clauses(db):
    return [
        clause.get("id")
        for clause in (db.get("clauses") or [])
        if len(list(clause.get("body") or [])) < 1
    ]
