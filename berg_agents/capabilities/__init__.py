"""Capability layer: protocol, base class, risk classes and preset specs.

Exposes the public names of the OAP-inspired capability contract plus the
config-driven preset schema (:mod:`berg_agents.capabilities.specs`) and
its resolver (:mod:`berg_agents.capabilities.spec_loader`).
"""

from __future__ import annotations

from .base import Capability, CapabilityBase, RiskClass
from .spec_loader import (
    harness_capability_from_spec,
    load_capability_specs,
    load_presets,
    load_toolset_specs,
    resolve_preset,
)
from .specs import CapabilitySpec, PresetSpec, ToolsetSpec

__all__ = [
    "Capability",
    "CapabilityBase",
    "CapabilitySpec",
    "PresetSpec",
    "RiskClass",
    "ToolsetSpec",
    "harness_capability_from_spec",
    "load_capability_specs",
    "load_presets",
    "load_toolset_specs",
    "resolve_preset",
]
