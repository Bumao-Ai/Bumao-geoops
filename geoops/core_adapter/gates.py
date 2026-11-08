"""Host gates for Bumao GeoOps, assembled from Bumao Core shared templates.

Every gate receives its data through an injected callable, as the kernel's
template contract requires.
"""

GATE_LABELS = {
    "B1": "rule ids are unique",
    "B2": "rule blocks stay contiguous",
    "B3": "no empty rule shells",
    "B4": "no broken rule references",
}


def _clause_reader(rules_db):
    def read():
        return rules_db.index(rules_db.load())["clauses"]

    return read


def _bool_gate(check_fn):
    """Adapt a core template gate (``(ok, detail)``) to a bool gate.

    ``GateRegistry.run_all`` uses ``bool(fn())``; a ``(False, detail)`` tuple
    would be truthy there. This adapter keeps the registry verdict honest.
    """

    def gate():
        result = check_fn()
        if isinstance(result, tuple) and len(result) >= 2:
            return bool(result[0])
        return bool(result)

    gate.__name__ = getattr(check_fn, "__name__", "gate")
    return gate


def build(rules_db):
    """Return ``{gate_id: check_fn}`` for the current host rules module."""
    import bumao_core_gates as templates

    clauses = _clause_reader(rules_db)
    return {
        "B1": _bool_gate(templates.make_unique_ids_gate(clauses_func=clauses)),
        "B2": _bool_gate(templates.make_block_broken_gate(clauses_func=clauses)),
        "B3": _bool_gate(templates.make_shell_clauses_gate(clauses_func=clauses)),
        "B4": _bool_gate(templates.make_broken_refs_gate(clauses_func=clauses)),
    }
