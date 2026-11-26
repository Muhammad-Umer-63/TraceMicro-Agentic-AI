"""Scenario-level masking/recovery plumbing; contains no actual runtime traces."""
import copy


class ScenarioEvidence:
    def __init__(self, scenarios, availability):
        if availability not in (0, 0.5, 1):
            raise ValueError('Availability must be 0, 0.5 or 1')
        self.scenarios = copy.deepcopy(scenarios)
        names = sorted(scenarios)
        count = int(len(names)*availability)
        self.visible = set(names[:count])
        self.initial = sorted(self.visible)
        self.recovery_calls = 0

    def read_visible(self):
        return {name: copy.deepcopy(self.scenarios[name]) for name in sorted(self.visible)}

    def recover(self, scenario):
        self.recovery_calls += 1
        if scenario not in self.scenarios:
            raise ValueError('Scenario unavailable in permitted collection pool')
        self.visible.add(scenario)
        return copy.deepcopy(self.scenarios[scenario])
