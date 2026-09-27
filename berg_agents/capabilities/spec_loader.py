"""Resolve config-driven toolset / capability presets (Phase 2).

The loader reads the raw ``toolsets`` / ``capabilities`` / ``presets``
mappings from a config dict (``Settings.model_dump()`` or a parsed
``bergagents.jsonc`` block) and turns them into typed
:mod:`berg_agents.capabilities.specs` models. It performs no registration
and touches no existing dispatch path, so importing it changes nothing.

Resolution order for :func:`resolve_preset`:

1. global ``toolsets.default`` + ``capabilities.default`` always apply;
2. every entry in ``presets`` whose ``models`` glob matches ``model_id``
   *and* whose ``agents`` contains ``agent_name`` (empty selector lists
   match everything) merges its ``toolsets`` / ``capabilities`` in order;
3. duplicates are removed, first occurrence wins.

:func:`harness_capability_from_spec` adapts one :class:`CapabilitySpec`
to a ``pydantic_ai_harness`` capability instance. Unknown ids return
``None`` so ours-native capabilities keep working untouched.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
import fnmatch
import importlib
import inspect
import logging
from typing import Any

from .specs import CapabilitySpec, PresetSpec, ToolsetSpec

#: Module logger used when a single malformed preset is skipped.
logger = logging.getLogger(__name__)


def _normalized(name: str) -> str:
    """Normalize an id for harness lookup (dashes == underscores, lowercase).

    :param name: Raw capability or module id.
    :return: Normalized lookup key.
    """
    return name.strip().lower().replace("-", "_")


def _as_list(value: Any) -> list[str]:
    """Coerce a config value to a list of strings, dropping non-strings.

    :param value: Raw config node (list, single string, or anything else).
    :return: Clean list of strings (empty when the node is not usable).
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def load_toolset_specs(cfg: Mapping[str, Any]) -> dict[str, ToolsetSpec]:
    """Parse the ``toolsets`` config block into named specs.

    Accepts the ``{"default": [...], "builtin": {...}, "custom": {...}}``
    shape; entries under ``builtin`` / ``custom`` may be either option
    dicts (``{"includes": [...], "excludes": [...]}``) or plain include
    lists. The ``default`` name list is stored under the reserved key
    ``"default"`` as a :class:`ToolsetSpec` whose ``includes`` are the
    default toolset *names* (resolved by :func:`resolve_preset`, not here).

    :param cfg: Raw config mapping (may lack ``toolsets`` entirely).
    :return: Mapping of toolset name to :class:`ToolsetSpec`.
    """
    node = cfg.get("toolsets")
    if not isinstance(node, Mapping):
        return {}
    specs: dict[str, ToolsetSpec] = {}
    for section, builtin in (("builtin", True), ("custom", False)):
        entries = node.get(section)
        if not isinstance(entries, Mapping):
            continue
        for name, raw in entries.items():
            if isinstance(raw, Mapping):
                specs[str(name)] = ToolsetSpec(
                    name=str(name),
                    includes=_as_list(raw.get("includes")),
                    excludes=_as_list(raw.get("excludes")),
                    builtin=builtin,
                    description=str(raw.get("description", "")),
                )
            else:
                # Plain list form: the value is the include list.
                specs[str(name)] = ToolsetSpec(
                    name=str(name), includes=_as_list(raw), builtin=builtin
                )
    default_names = _as_list(node.get("default"))
    if default_names:
        specs["default"] = ToolsetSpec(name="default", includes=default_names)
    return specs


def load_capability_specs(cfg: Mapping[str, Any]) -> dict[str, CapabilitySpec]:
    """Parse the ``capabilities`` config block into specs keyed by id.

    Accepts ``{"default": [...], "custom": {"memory": {...options...}}}``;
    ``default`` entries may be plain ids or single-key option dicts.
    The ``default`` id list is stored under the reserved key ``"default"``
    as a :class:`CapabilitySpec` whose ``options`` carry the default id
    list under the ``"defaults"`` key (resolved by :func:`resolve_preset`).

    :param cfg: Raw config mapping (may lack ``capabilities`` entirely).
    :return: Mapping of capability id to :class:`CapabilitySpec`.
    """
    node = cfg.get("capabilities")
    if not isinstance(node, Mapping):
        return {}
    specs: dict[str, CapabilitySpec] = {}
    entries = node.get("custom")
    if isinstance(entries, Mapping):
        for cap_id, raw in entries.items():
            if isinstance(raw, Mapping):
                specs[str(cap_id)] = CapabilitySpec(
                    id=str(cap_id),
                    enabled=bool(raw.get("enabled", True)),
                    options={
                        key: value
                        for key, value in raw.items()
                        if key not in {"enabled", "defer_loading"}
                    },
                    defer_loading=bool(raw.get("defer_loading", False)),
                )
            elif isinstance(raw, bool):
                # Shorthand: ``"memory": false`` disables the capability.
                specs[str(cap_id)] = CapabilitySpec(id=str(cap_id), enabled=raw)
    default_ids = _as_list(node.get("default"))
    if default_ids:
        specs["default"] = CapabilitySpec(
            id="default", options={"defaults": default_ids}
        )
    return specs


def load_presets(cfg: Mapping[str, Any]) -> list[PresetSpec]:
    """Parse the ``presets`` config list into validated specs.

    Malformed entries are skipped rather than raising, so a typo in one
    preset cannot break agent startup.

    :param cfg: Raw config mapping (may lack ``presets`` entirely).
    :return: List of valid :class:`PresetSpec` entries in config order.
    """
    raw = cfg.get("presets")
    if not isinstance(raw, (list, tuple)):
        return []
    presets: list[PresetSpec] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        try:
            presets.append(
                PresetSpec(
                    name=str(entry.get("name", "unnamed")),
                    models=_as_list(entry.get("models")),
                    agents=_as_list(entry.get("agents")),
                    toolsets=_as_list(entry.get("toolsets")),
                    capabilities=_as_list(entry.get("capabilities")),
                )
            )
        except Exception as exc:
            # Skip one bad preset instead of failing the whole load.
            logger.warning("skipping malformed preset %r: %s", entry, exc)
            continue
    return presets


def _preset_matches(preset: PresetSpec, model_id: str, agent_name: str) -> bool:
    """Check whether a preset applies to a model / agent combination.

    Empty selector lists match everything; model entries are glob
    patterns (``fnmatch``), agent entries are exact matches.

    :param preset: The preset to test.
    :param model_id: Model id being resolved, e.g. ``"ollama:qwen3.5:9b"``.
    :param agent_name: Agent name, e.g. ``"implementation"``.
    :return: True when the preset applies.
    """
    models_ok = not preset.models or any(
        fnmatch.fnmatch(model_id, pattern) for pattern in preset.models
    )
    agents_ok = not preset.agents or agent_name in preset.agents
    return bool(models_ok and agents_ok)


def resolve_preset(
    model_id: str,
    agent_name: str,
    cfg: Mapping[str, Any],
    toolset_specs: dict[str, ToolsetSpec] | None = None,
    capability_specs: dict[str, CapabilitySpec] | None = None,
) -> PresetSpec:
    """Resolve the effective toolset / capability selection.

    Merges global defaults (``toolsets.default``, ``capabilities.default``)
    with every matching ``presets`` entry in config order. Names that have
    no corresponding spec are kept (callers decide whether unknown names
    are an error), so resolution never drops user intent silently.

    :param model_id: Model id being resolved.
    :param agent_name: Agent name being resolved.
    :param cfg: Raw config mapping.
    :param toolset_specs: Pre-loaded toolset specs (loaded when omitted).
    :param capability_specs: Pre-loaded capability specs (loaded when omitted).
    :return: Synthetic :class:`PresetSpec` named ``"resolved:<agent>@<model>"``.
    """
    toolset_specs = (
        toolset_specs if toolset_specs is not None else load_toolset_specs(cfg)
    )
    capability_specs = (
        capability_specs
        if capability_specs is not None
        else load_capability_specs(cfg)
    )
    toolsets: list[str] = []
    capabilities: list[str] = []

    default_toolset = toolset_specs.get("default")
    if default_toolset is not None:
        toolsets.extend(default_toolset.includes)
    default_cap = capability_specs.get("default")
    if default_cap is not None:
        capabilities.extend(_as_list(default_cap.options.get("defaults")))

    for preset in load_presets(cfg):
        if _preset_matches(preset, model_id, agent_name):
            toolsets.extend(preset.toolsets)
            capabilities.extend(preset.capabilities)

    # De-duplicate, first occurrence wins (defaults keep priority).
    toolsets = list(dict.fromkeys(toolsets))
    capabilities = list(dict.fromkeys(capabilities))
    return PresetSpec(
        name=f"resolved:{agent_name}@{model_id}",
        models=[model_id],
        agents=[agent_name],
        toolsets=toolsets,
        capabilities=capabilities,
    )


# Explicit aliases where the capability id does not trivially map to the
# harness ``(module, class)`` pair via dash-to-PascalCase conversion.
_HARNESS_ALIASES: dict[str, tuple[str, str]] = {
    "code_mode": ("code_mode", "CodeMode"),
    "repo_context": ("repo_context", "RepoContext"),
    "conversation_search": ("conversation_search", "ConversationSearch"),
    "step_persistence": ("step_persistence", "StepPersistence"),
    "system_reminders": ("system_reminders", "SystemReminders"),
    "prompt_injection_defender": (
        "prompt_injection_defender",
        "PromptInjectionDefender",
    ),
}


def _class_name(key: str) -> str:
    """Derive the PascalCase class name from a normalized capability key.

    :param key: Normalized id (lowercase, underscores), e.g. ``"code_mode"``.
    :return: Class name, e.g. ``"CodeMode"``.
    """
    return "".join(part.capitalize() for part in key.split("_"))


def _harness_class(cap_id: str) -> type | None:
    """Import and return the capability class for an id.

    Resolution order (first hit wins):

    1. top-level ``pydantic_ai_harness.<Class>`` lazy export — covers
       ``Coder``, ``Researcher``, ``FileSystem`` and the rest per the
       official harness docs (``capabilities=[Coder()]``);
    2. ``pydantic_ai_harness.<module>.<Class>`` submodule convention;
    3. core ``pydantic_ai.capabilities.<Class>`` — covers ``WebSearch``,
       ``WebFetch``, ``Thinking``, ``MCP`` and friends.

    :param cap_id: Capability id, e.g. ``"filesystem"`` or ``"web-search"``.
    :return: The capability class, or None when the id is unknown
        (ours-native capabilities fall through to None so they keep
        working untouched).
    """
    key = _normalized(cap_id)
    name = _class_name(key)
    import pydantic_ai_harness as harness_pkg

    candidate = getattr(harness_pkg, name, None)
    if isinstance(candidate, type):
        return candidate
    module_name, class_name = _HARNESS_ALIASES.get(key, (key, name))
    module = importlib.import_module(f"pydantic_ai_harness.{module_name}")
    if not isinstance(candidate, type):
        # Fall back to the `<Class>Toolset` variant some modules expose.
        candidate = getattr(module, f"{class_name}Toolset", None)
    if isinstance(candidate, type):
        return candidate
    from pydantic_ai import capabilities as core_capabilities

    candidate = getattr(core_capabilities, name, None)
    if isinstance(candidate, type):
        return candidate
    return None


def harness_capability_from_spec(spec: CapabilitySpec) -> Any | None:
    """Build a ``pydantic_ai_harness`` capability from a spec.

    Unknown option keys are filtered against the constructor signature so
    config typos degrade to ignored keys instead of ``TypeError``. When
    ``defer_loading`` is set and the instance exposes a ``defer_loading``
    hook, it is invoked before returning.

    :param spec: The capability spec to adapt.
    :return: A harness capability instance, or None for unknown ids.
    """
    cls = _harness_class(spec.id)
    if cls is None:
        return None
    try:
        accepted = set(inspect.signature(cls.__init__).parameters)
    except (TypeError, ValueError):
        accepted = set()
    accepted.discard("self")
    kwargs = {
        key: value for key, value in spec.options.items() if key in accepted
    }
    try:
        instance = cls(**kwargs)
    except Exception:
        return None
    if spec.defer_loading:
        hook = getattr(instance, "defer_loading", None)
        if callable(hook):
            with suppress(Exception):
                instance = hook() or instance
    return instance
