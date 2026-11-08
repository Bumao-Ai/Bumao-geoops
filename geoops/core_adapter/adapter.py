"""Core adapter: the GeoOps-side entry to real Bumao Core interfaces."""

from geoops.core_adapter import core, gates, rules_db

EDITION_NAME = "Bumao GeoOps"


class CoreAdapter:
    """Wire host rules and gates into the kernel, then run its gate registry."""

    def __init__(self, rules_module=None):
        self.core, self.registry_module, self.templates = core.load()
        self.rules_db = rules_module or rules_db
        self.expected = frozenset()

    def surface(self):
        return core.surface(self.core)

    def wire(self):
        """Call the kernel's real configure/register/set_expected interfaces."""
        self.core.configure(rules_db_module=self.rules_db)
        mapping = gates.build(self.rules_db)
        for gate_id in sorted(mapping):
            self.core.register(gate_id, mapping[gate_id], gates.GATE_LABELS[gate_id])
        self.expected = frozenset(mapping)
        self.core.set_expected("B", self.expected)
        return self.expected

    def verify(self):
        """Call the kernel's real anti-shrink verification."""
        return bool(self.core.verify_registration(self.expected, EDITION_NAME))

    def registered_gates(self):
        return list(self.registry_module.get_registered_ids())

    def run_gates(self):
        """Use the kernel's GateRegistry to validate and run every host gate."""
        registry = self.registry_module.GateRegistry(
            engine_module=self.core, name="bumao-geoops"
        )
        registry.validate(self.expected)
        return registry.run_all()
