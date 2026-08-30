"""CodeAgents (DeepAgents) (LangGraph) based agent construction.

This module builds on :func:`deepagents.create_deep_agent` and centralizes
the project-specific wiring that a plain ``create_agent`` call does not
cover:

* the working directory is mounted at ``/workspace/`` through a
  :class:`~deepagents.backends.composite.CompositeBackend` - the project
  lives on real disk (``FilesystemBackend`` with ``virtual_mode=True`` for
  path sandboxing) while agent-internal artifacts (offloaded tool results
  under ``/large_tool_results/`` and conversation history under
  ``/conversation_history/``) stay in an ephemeral
  :class:`~deepagents.backends.state.StateBackend` instead of polluting the
  user's project,
* path permissions (``FilesystemPermission`` glob rules) with
  ``mode="interrupt"`` pause the built-in filesystem tools for
  human-in-the-loop review,
* ``interrupt_on`` gates the mutating built-in tools (``edit_file``,
  ``write_file``, ``delete``, ``execute``) and any custom tools the caller
  marks for review,
* an :class:`langgraph.checkpoint.memory.InMemorySaver` checkpointing is
  attached automatically (mandatory for HITL pauses to work),
* optional *harness profiles* (registered under ``provider:model`` keys) tune
  the system prompt, tool descriptions and excluded tools per model.  By
  default, :func:`build_berg_agents` loads them from the user-editable config
  file ``/home/nvidia/berg_agents/config/profiles.yaml`` (see
  :data:`~berg_agents.profiles.router.DEFAULT_PROFILES_CONFIG`); pass
  ``register_profiles=False`` to launch without them.
* *skills* (``SKILL.md`` sources loaded progressively) and *memory*
  (``AGENTS.md`` files always loaded) are translated to workspace-virtual
  paths (:func:`_resolve_workspace_paths`) and forwarded to
  ``create_deep_agent``,
* a :class:`~langchain.agents.middleware.TodoListMiddleware` (``write_todos``
  tool) is added by default unless ``todos_enabled=False``,
* explicit summarization thresholds (``summarization_trigger`` /
  ``summarization_keep``) replace the harness's built-in
  :class:`~deepagents.middleware.SummarizationMiddleware` with a configured
  one (context offloading / ``compact_conversation``).

The built-in filesystem tool set provided by ``create_deep_agent`` is
``ls, read_file, write_file, edit_file, glob, grep, delete, execute, task``.
Passing custom tools is *additive* - built-ins are only removed through a
profile's ``excluded_tools``.  This module therefore drops custom tools whose
names collide with the built-ins (the built-ins are the ones wired to the
backend/permissions, so they win), avoiding duplicate-tool errors.
"""

from __future__ import annotations

from builtins import ValueError
from collections.abc import Iterable, Mapping, Sequence
import logging
from pathlib import Path
from typing import Any, cast

from berg_agents.config.settings import get_settings
from berg_agents.profiles.router import (
    DEFAULT_PROFILES_CONFIG,
    register_profiles_from_config_file,
    register_profiles_from_settings,
)
from deepagents import (
    FilesystemPermission,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import CompositeBackend, StateBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware import SummarizationMiddleware
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
from langchain.agents.middleware.summarization import ContextSize, TriggerClause
from langchain.chat_models import BaseChatModel
from langchain.messages import SystemMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

log = logging.getLogger(__name__)

__all__ = [
    "FS_BUILTIN_TOOLS",
    "_resolve_workspace_paths",
    "build_agent",
    "build_berg_agents",
    "create_default_tools",
    "make_backend",
    "make_default_permissions",
    "register_harness_profile",
]

#: Tools provided out of the box by ``create_deep_agent``.
FS_BUILTIN_TOOLS: frozenset[str] = frozenset({
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "delete",
    "execute",
    "task",
})

#: Built-in tools that modify state and therefore default to HITL review.
DEFAULT_INTERRUPT_ON: dict[str, bool] = {
    "edit_file": True,
    "write_file": True,
    "delete": True,
    "execute": True,
}

#: Route prefix under which the real working directory is mounted.
DEFAULT_WORKSPACE_PREFIX = "/workspace/"

#: Default base system prompt used when no explicit ``system_prompt`` is passed
#: and no harness profile (which would supply a ``system_prompt_suffix``) is in
#: effect.  It explicitly tells the model that project files live under the
#: ``/workspace`` virtual mount so it stops probing unreachable host-relative
#: paths and reporting "no files accessible".
DEFAULT_BASE_SYSTEM_PROMPT = (
    "You are a helpful assistant. "
    "Workspace files are mounted at /workspace (maps to the project working "
    "directory). Always use the /workspace prefix with filesystem tools, e.g. "
    'ls(path="/workspace"), read_file(path="/workspace/README.md"), '
    'glob(pattern="**/*.py", path="/workspace").'
)


def make_backend(
    root_dir: str | Path,
    *,
    workspace_prefix: str = DEFAULT_WORKSPACE_PREFIX,
    virtual_mode: bool = True,
) -> CompositeBackend:
    """Build the :class:`CompositeBackend` used by the deep agent.

    Routes ``<workspace_prefix>`` to a real-disk :class:`FilesystemBackend`
    rooted at *root_dir* (``virtual_mode=True`` sandboxes paths: ``..``,
    ``~`` and absolute paths outside the root are blocked).  Everything else
    - the agent's internal files - stays in an ephemeral :class:`StateBackend`
    so offloaded tool results and conversation history never touch the user's
    project.

    :param root_dir: Directory the agent may read/write on real disk.
    :param workspace_prefix: Virtual mount point for *root_dir* (must start
        and end with ``/``).
    :param virtual_mode: Sandbox paths under *root_dir* (recommended; the
        non-virtual mode provides no path security at all).

    :return: A configured :class:`CompositeBackend`.
    """
    fs_backend = FilesystemBackend(
        root_dir=str(Path(root_dir).expanduser().resolve()),
        virtual_mode=virtual_mode,
    )
    return CompositeBackend(StateBackend(), {workspace_prefix: fs_backend})


def make_default_permissions(
    *,
    workspace_prefix: str = DEFAULT_WORKSPACE_PREFIX,
) -> list[FilesystemPermission]:
    """Return sensible default filesystem permission rules.

    Rules are evaluated in order, first match wins, and any path that matches
    no rule is *allowed* - so the deny rules must come before the allow-all.

    * reads under the workspace are allowed,
    * writes under the workspace raise an HITL interrupt (``mode="interrupt"``
      pauses the built-in ``write_file``/``edit_file`` tools for review),
    * ``.env`` and ``secrets/`` are denied outright (defense in depth on top
      of ``virtual_mode``).

    All patterns are glob rules (``**`` crosses directories) matched against
    the validated route-prefixed path, e.g. ``/workspace/foo/bar.py``.

    :param workspace_prefix: Route prefix of the real working directory.

    :return: Ordered list of :class:`FilesystemPermission` rules.
    """
    wp = workspace_prefix.rstrip("/")  # e.g. "/workspace"
    return [
        # Deny sensitive paths first (first-match-wins semantics).
        FilesystemPermission(
            operations=["read", "write"],
            paths=[f"{wp}/.env", f"{wp}/**/.env", f"{wp}/secrets/**"],
            mode="deny",
        ),
        # Reads: allowed anywhere under the workspace.
        FilesystemPermission(
            operations=["read"],
            paths=[f"{wp}/**"],
            mode="allow",
        ),
        # Writes: paused for human review.
        FilesystemPermission(
            operations=["write"],
            paths=[f"{wp}/**"],
            mode="interrupt",
        ),
    ]


def _resolve_workspace_paths(
    paths: Sequence[str | tuple[str, str]],
    root_dir: str | Path,
    workspace_prefix: str = DEFAULT_WORKSPACE_PREFIX,
) -> list[str | tuple[str, str]]:
    """Translate on-disk skill/memory paths into workspace-virtual paths.

    deepagents loads skills and memory through the configured backend, which
    for this project routes the virtual ``<workspace_prefix>`` subtree to
    *root_dir* on real disk.  Sources must therefore be expressed in virtual
    form (``/workspace/...``) or be translated here:

    * already-virtual paths under ``<workspace_prefix>`` pass through
      unchanged,
    * paths under *root_dir* are re-rooted to the virtual prefix,
    * relative paths resolve against *root_dir* first,
    * anything outside the workspace raises :class:`ValueError` (skills and
      memory must live under the mounted workspace so the backend can read
      them).

    Tuple entries ``(path, label)`` (the ``SkillsMiddleware`` source form) are
    preserved; only the path half is translated.

    :param paths: Skill/memory sources: bare paths or ``(path, label)`` tuples.
    :param root_dir: Real working directory mounted at *workspace_prefix*.
    :param workspace_prefix: Virtual mount point for *root_dir*.

    :return: Sources with the path half translated to virtual form.
    """
    root = Path(root_dir).expanduser().resolve()
    prefix = workspace_prefix.rstrip("/")  # e.g. "/workspace"

    def _translate(path: str) -> str:
        """

        :param path: Path to translate (bare or already-virtual).
        :return: Virtualized path under *workspace_prefix*.
        """
        p = Path(path).expanduser()
        # Already-virtual: under the workspace prefix -> unchanged.
        if p.is_absolute() and p.is_relative_to(Path(prefix)):
            return path
        if p.is_absolute():
            resolved = p.resolve()
            if resolved.is_relative_to(root):
                return f"{prefix}/{resolved.relative_to(root)}"
            # Absolute path outside the workspace -> reject.
            raise ValueError(
                f"Path {path!r} is outside the workspace root {root!r}; "
                f"skills/memory must live under the mounted workspace"
            )
        # Relative path: resolve against the workspace root.
        resolved = (root / p).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(
                f"Relative path {path!r} escapes the workspace root {root!r}"
            )
        return f"{prefix}/{resolved.relative_to(root)}"

    translated: list[str | tuple[str, str]] = []
    for entry in paths:
        if isinstance(entry, tuple):
            path, label = entry
            translated.append((_translate(path), label))
        else:
            translated.append(_translate(entry))
    return translated


#: Length of the ``(kind, value)`` context-size pair form (e.g. ``["messages", 50]``).
_CONTEXT_SIZE_PAIR_LEN = 2


def _normalize_context_size(value: Any) -> Any:
    """Normalize a JSON-parsed context-size spec to middleware form.

    Settings arrive as JSON, so ``["messages", 50]`` is a *list*; the
    summarization middleware only accepts tuples (``("messages", 50)``),
    :class:`TriggerClause` dicts, or lists of either.  This converts the
    two-element list form to a tuple and recurses into OR-lists.

    :param value: Raw trigger/keep spec from settings or call-site.
    :return: Normalized spec acceptable to the summarization middleware.
    """
    if isinstance(value, list):
        if len(value) == _CONTEXT_SIZE_PAIR_LEN and isinstance(value[0], str):
            return value[0], value[1]
        return [_normalize_context_size(item) for item in value]
    return value


def _assemble_middleware(
    *,
    base: Sequence[Any],
    todos_enabled: bool,
    summarization_trigger: Any,
    summarization_keep: Any,
    llm: BaseChatModel,
    backend: Any,
) -> tuple[Any, ...]:
    """Assemble the extra middleware stack for the agent.

    deepagents already ships Filesystem/SubAgent/Summarization middleware; we
    only add what the caller (or settings) explicitly asked for:

    * :class:`TodoListMiddleware` (``write_todos`` tool) unless opted out, and
    * a configured :class:`SummarizationMiddleware` when explicit trigger/keep
      thresholds are set - it replaces the built-in by name.

    Middleware already present in *base* (matched by ``.name``) is never
    duplicated.

    :param base: Middleware passed by the caller via ``kwargs``.
    :param todos_enabled: Whether to add the todo-list middleware.
    :param summarization_trigger: Explicit trigger spec, or ``None``.
    :param summarization_keep: Retention policy, or ``None``.
    :param llm: Chat model backing the agent.
    :param backend: Filesystem backend for summarization offloading.
    :return: The assembled middleware tuple (empty when nothing to add).
    """
    middleware = list(base)
    middleware_names = {m.name for m in middleware}
    if todos_enabled and "TodoListMiddleware" not in middleware_names:
        middleware.append(TodoListMiddleware())
    if summarization_trigger is not None and (
        "SummarizationMiddleware" not in middleware_names
    ):
        middleware.append(
            SummarizationMiddleware(
                model=llm,
                backend=backend,
                trigger=summarization_trigger,
                keep=summarization_keep or ("messages", 20),
            )
        )
    return tuple(middleware)


def _resolve_agent_options(
    *,
    skills: Sequence[str | tuple[str, str]] | None,
    memory: Sequence[str] | None,
    todos_enabled: bool | None,
    summarization_trigger: Any,
    summarization_keep: Any,
    settings: Any,
) -> tuple[
    Sequence[str | tuple[str, str]] | None,
    Sequence[str] | None,
    bool,
    Any,
    Any,
]:
    """Resolve skills/memory/todos/summarization options.

    Explicit call-site values win; otherwise the user-configurable defaults
    from *settings* (bergagents.jsonc / .env) apply.  Settings arrive as JSON,
    so list-form context sizes are normalized to the tuple/TriggerClause
    forms the summarization middleware accepts, and two-element skill source
    lists become ``(path, label)`` tuples.

    :param skills: Call-site skills, or ``None``.
    :param memory: Call-site memory, or ``None``.
    :param todos_enabled: Call-site todo flag, or ``None``.
    :param summarization_trigger: Call-site trigger, or ``None``.
    :param summarization_keep: Call-site keep, or ``None``.
    :param settings: Settings instance providing defaults.
    :return: Resolved ``(skills, memory, todos_enabled, trigger, keep)``.
    """
    skills_sources: Sequence[str | tuple[str, str]] | None = skills
    memory_sources: Sequence[str] | None = memory
    if skills_sources is None:
        raw_skills = settings.skills
        if raw_skills:
            # Settings may carry skill sources as JSON arrays; a two-element
            # list is the ``(path, label)`` form and is normalized to a tuple
            # for _resolve_workspace_paths.
            skills_sources = cast(
                list[str | tuple[str, str]],
                [
                    tuple(entry) if isinstance(entry, list) else entry
                    for entry in raw_skills
                ],
            )
    if memory_sources is None:
        memory_sources = settings.memory
    resolved_todos = (
        todos_enabled if todos_enabled is not None else settings.todos_enabled
    )
    if summarization_trigger is None:
        summarization_trigger = settings.summarization_trigger
    if summarization_keep is None:
        summarization_keep = settings.summarization_keep

    return (
        skills_sources,
        memory_sources,
        resolved_todos,
        _normalize_context_size(summarization_trigger),
        _normalize_context_size(summarization_keep),
    )


def build_berg_agents(
    llm: BaseChatModel,
    tools: Sequence[BaseTool] | None = None,
    *,
    root_dir: str | Path = ".",
    system_prompt: str | SystemMessage | None = None,
    permissions: Sequence[FilesystemPermission] | None = None,
    interrupt_on: Mapping[str, bool | InterruptOnConfig] | None = None,
    checkpointer: Any | None = None,
    store: BaseStore | None = None,
    name: str | None = None,
    workspace_prefix: str = DEFAULT_WORKSPACE_PREFIX,
    drop_builtin_collisions: bool = True,
    profile: HarnessProfile | None = None,
    profile_key: str | None = None,
    register_profiles: bool = True,
    profiles_config: str | Path | None = None,
    skills: Sequence[str | tuple[str, str]] | None = None,
    memory: Sequence[str] | None = None,
    todos_enabled: bool | None = None,
    summarization_trigger: (
        ContextSize | TriggerClause | list[ContextSize | TriggerClause] | None
    ) = None,
    summarization_keep: ContextSize | None = None,
    **kwargs: Any,
) -> CompiledStateGraph:
    """Create a DeepAgents agent wired for this project.

    The returned graph exposes the built-in filesystem tools plus any custom
    *tools* that do not collide with those built-ins.  All mutating built-ins
    default to HITL review (see :data:`DEFAULT_INTERRUPT_ON`); merge
    additional tool names into *interrupt_on* (``True`` or a dict with
    ``allowed_decisions``) to review custom tools as well.

    A checkpointer is mandatory for HITL; when none is given an
    :class:`InMemorySaver` is created (per-thread, in-memory).

    :param llm: Chat model backing the agent.
    :param tools: Custom tools to add on top of the built-in filesystem set.
        Tools whose ``name`` collides with a built-in are dropped unless
        *drop_builtin_collisions* is false.
    :param root_dir: Real working directory mounted at *workspace_prefix*.
    :param system_prompt: Base system prompt for the agent.
    :param permissions: Filesystem permission rules; defaults to
        :func:`make_default_permissions`.
    :param interrupt_on: Tool-name -> HITL config.  Defaults to
        :data:`DEFAULT_INTERRUPT_ON` (mutating built-ins).
    :param checkpointer: LangGraph checkpointer; an :class:`InMemorySaver` is
        created when omitted.
    :param store: Optional LangGraph store (cross-thread memory).
    :param name: Optional graph name (useful for tracing).
    :param workspace_prefix: Virtual mount point for *root_dir*.
    :param drop_builtin_collisions: Drop custom tools whose names match
        built-in tools (built-ins are wired to the backend and win).
    :param profile: Optional harness profile to register under *profile_key*.
    :param profile_key: Key of the form ``provider:model`` (e.g.
        ``"ollama:gpt-oss"``) or a bare provider (e.g. ``"ollama"``) under
        which *profile* is registered.  Note: a model identifier that itself
        contains a ``:`` (such as ``gpt-oss:20b``) cannot be used as an exact
        ``provider:model`` key - register it under the bare provider key.
    :param register_profiles: When true (default), register every harness
        profile declared in the config file at *profiles_config* (default
        :data:`DEFAULT_PROFILES_CONFIG`, i.e.
        ``/home/nvidia/berg_agents/config/profiles.yaml``) before building the
        agent.  Pass false to launch without any config-file profiles.
    :param profiles_config: Override path for the profiles config file; only
        used when *register_profiles* is true.
    :param skills: Skill source paths (bare paths or ``(path, label)`` tuples)
        loaded progressively by the harness.  Paths are translated to
        workspace-virtual form via :func:`_resolve_workspace_paths`; when
        ``None`` the value falls back to ``settings.skills``.
    :param memory: ``AGENTS.md`` memory file paths, always loaded into the
        agent's context.  Translated like *skills*; when ``None`` the value
        falls back to ``settings.memory``.
    :param todos_enabled: When true (default), a
        :class:`~langchain.agents.middleware.TodoListMiddleware` is added so
        the agent can maintain a structured ``write_todos`` task list.  When
        ``None`` the value falls back to ``settings.todos_enabled``.
    :param summarization_trigger: Explicit summarization threshold(s)
        (``("fraction", 0.85)``, ``("messages", 50)``, a
        :class:`~langchain.agents.middleware.summarization.TriggerClause`
        dict, or a list mixing either form).  When set, a
        :class:`~deepagents.middleware.SummarizationMiddleware` configured
        with this trigger replaces the harness's built-in one.  When ``None``
        the value falls back to ``settings.summarization_trigger`` (and the
        harness default applies when that is unset too).
    :param summarization_keep: Context retention policy after summarization
        (e.g. ``("messages", 20)``).  Only used together with
        *summarization_trigger*; falls back to ``settings.summarization_keep``.
    :param kwargs: Extra keyword arguments forwarded to
        :func:`deepagents.create_deep_agent` (e.g. ``middleware``,
        ``subagents``, ``response_format``, ``debug``).

    :return: A compiled LangGraph state graph ready to ``invoke``.
    """
    # Settings fallback: explicit call-site values win; otherwise the
    # user-configurable defaults from Settings (bergagents.jsonc / .env) apply.
    settings = get_settings()
    (
        skills_sources,
        memory_sources,
        todos_enabled,
        summarization_trigger,
        summarization_keep,
    ) = _resolve_agent_options(
        skills=skills,
        memory=memory,
        todos_enabled=todos_enabled,
        summarization_trigger=summarization_trigger,
        summarization_keep=summarization_keep,
        settings=settings,
    )

    backend = make_backend(root_dir, workspace_prefix=workspace_prefix)

    # Register all harness profiles from the user-editable config file by
    # default (see berg_agents.profiles.router.DEFAULT_PROFILES_CONFIG, i.e.
    # /home/nvidia/berg_agents/config/profiles.yaml).  Pass
    # register_profiles=False to launch without them, or profiles_config to
    # point at a different file.
    if register_profiles:
        config_path = (
            Path(profiles_config)
            if profiles_config
            else DEFAULT_PROFILES_CONFIG
        )
        register_profiles_from_config_file(config_path)
        # Also apply any profiles declared in the main app config
        # (bergagents.jsonc / bergagents.yaml via the ``profiles`` key, or the
        # BERG_AGENT_PROFILES env entry) so both config surfaces load by default.
        register_profiles_from_settings()

    # Custom tools are additive; drop any that shadow the built-ins.
    # Bare callables (e.g. ``py_to_ipynb``) are wrapped into StructuredTools
    # so they expose ``.name`` and play nicely with ``create_deep_agent``.
    tool_list: list[BaseTool] = []
    for item in tools or []:
        if isinstance(item, BaseTool):
            tool_list.append(item)
        elif callable(item):
            tool_list.append(StructuredTool.from_function(item))
        else:
            raise TypeError(
                f"Unsupported tool entry: {item!r} (expected BaseTool or callable)"
            )
    if drop_builtin_collisions and tool_list:
        original_names = {t.name for t in tool_list}
        tool_list = [t for t in tool_list if t.name not in FS_BUILTIN_TOOLS]
        dropped = original_names - {t.name for t in tool_list}
        if dropped:
            log.info(
                "Dropped custom tools shadowing built-ins: %s", sorted(dropped)
            )

    # HITL: default to reviewing every mutating built-in tool.
    merged_interrupt_on: dict[str, bool | InterruptOnConfig] = dict(
        DEFAULT_INTERRUPT_ON
    )
    if interrupt_on:
        merged_interrupt_on.update(interrupt_on)

    # A checkpointer is required for HITL pauses to be resumable.
    if checkpointer is None:
        checkpointer = InMemorySaver()

    if profile is not None:
        if not profile_key:
            raise ValueError(
                "profile_key (e.g. 'ollama:gpt-oss:20b') is required when a profile is given"
            )
        register_harness_profile(profile_key, profile)
        log.info("Registered harness profile under '%s'", profile_key)

    # Translate skills/memory sources to workspace-virtual paths so the
    # composite backend (which routes <workspace_prefix> to real disk) can
    # read them.  Tuple entries keep their display labels.
    skills_virtual = (
        _resolve_workspace_paths(skills_sources, root_dir, workspace_prefix)
        if skills_sources
        else None
    )
    memory_virtual = (
        _resolve_workspace_paths(memory_sources, root_dir, workspace_prefix)
        if memory_sources
        else None
    )

    # Assemble the extra middleware stack (todo list + explicit summarization
    # config); caller-supplied middleware is never duplicated by name.
    middleware = _assemble_middleware(
        base=kwargs.pop("middleware", ()) or (),
        todos_enabled=todos_enabled,
        summarization_trigger=summarization_trigger,
        summarization_keep=summarization_keep,
        llm=llm,
        backend=backend,
    )
    if middleware:
        kwargs["middleware"] = middleware

    # Fall back to a project-aware base prompt when none is supplied and no
    # harness profile (which would append a system_prompt_suffix) is in effect,
    # so the model learns where the project files live instead of probing
    # host-relative paths that the sandbox blocks.
    effective_system_prompt = (
        system_prompt
        if system_prompt is not None
        else DEFAULT_BASE_SYSTEM_PROMPT
    )

    # Materialize langchain's lazy _ConfigurableModel proxy (produced when
    # init_chat_model is called with configurable_fields="any") into a real
    # BaseChatModel. deepagents' resolve_model does `isinstance(model, BaseChatModel)`
    # which fails on the proxy, causing a 500 at agent build time. CLI and direct
    # consumers keep the proxy; only the deepagents path needs the concrete model.
    if not isinstance(llm, BaseChatModel):
        llm = llm._model()

    return create_deep_agent(
        model=llm,
        tools=tool_list or None,
        system_prompt=effective_system_prompt,
        backend=backend,
        permissions=(
            list(permissions)
            if permissions is not None
            else make_default_permissions(workspace_prefix=workspace_prefix)
        ),
        interrupt_on=merged_interrupt_on,
        checkpointer=checkpointer,
        store=store,
        name=name,
        # The installed deepagents types skills/memory as list[str], but the
        # runtime (SkillsMiddleware) accepts (path, label) tuples too.
        skills=skills_virtual,  # type: ignore[bad-argument-type]  # ty: ignore[invalid-argument-type]
        memory=memory_virtual,  # type: ignore[bad-argument-type]  # ty: ignore[invalid-argument-type]
        **kwargs,
    )


def build_agent(
    llm: BaseChatModel,
    tools: Iterable[BaseTool],
    *,
    root_dir: str | Path = ".",
    checkpointer: Any | None = None,
    **kwargs: Any,
) -> Runnable:
    """Build a CodeAgents agent with the given LLM and tools.

    This is the primary agent factory for the project. It wraps
    :func:`build_berg_agents` with the project's default backend, permissions,
    and profile configuration.

    :param llm: The language model to use.
    :param tools: The tools to bind to the LLM.
    :param root_dir: Working directory mounted at ``/workspace/``.
    :param checkpointer: Optional LangGraph checkpointer. When omitted, an
        :class:`InMemorySaver` is created automatically.
    :param kwargs: Extra keyword arguments forwarded to :func:`build_berg_agents`.
    :return: A compiled LangGraph state graph ready for execution.
    """
    return build_berg_agents(
        llm=llm,
        tools=list(tools),
        root_dir=root_dir,
        checkpointer=checkpointer,
        **kwargs,
    )


def create_default_tools(
    root_dir: str | None = None, llm: BaseChatModel | None = None
) -> list[BaseTool]:
    """Return the default tool set for the agent.

    Includes file tools, search/explain, test generation, formatting,
    notebook conversion, general chat, and R script execution. Tools that
    require an LLM are omitted when *llm* is ``None``.

    :param root_dir: The root directory for file tools.
    :param llm: Optional language model for tools that need it.
    :return: A list of :class:`BaseTool` instances.
    """
    from functools import wraps

    from berg_agents.tools import (
        edit_file,
        generate_test,
        make_format_code_tool,
        make_general_chat_tool,
        make_new_file_tool,
        make_r_script_tool,
        make_search_explain_tool,
        read_file,
    )
    from berg_agents.tools.notebook_tool import py_to_ipynb

    root_path = Path(root_dir) if root_dir else Path.cwd()

    def bind_root_dir(tool: BaseTool) -> BaseTool:
        """Bind the configured root directory to a function-based tool."""
        func = getattr(tool, "func", None) or tool.invoke
        root = root_path

        @wraps(func)
        def _bound(*args: Any, **kwargs: Any) -> Any:
            kwargs.pop("root_dir", None)
            return func(*args, root_dir=root, **kwargs)

        return StructuredTool.from_function(
            func=_bound,
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
        )

    standard_tools: list[BaseTool | None] = [
        bind_root_dir(read_file),
        bind_root_dir(edit_file),
        (
            make_search_explain_tool(root_dir=root_path, llm=llm)
            if llm
            else None
        ),
        make_new_file_tool(root_dir=root_path),
        bind_root_dir(generate_test),
        make_format_code_tool(root_dir=root_path),
        StructuredTool.from_function(py_to_ipynb),
        (make_general_chat_tool(llm=llm) if llm else None),
        make_r_script_tool(),
    ]

    tools: list[BaseTool] = [
        tool for tool in standard_tools if tool is not None
    ]

    return tools
