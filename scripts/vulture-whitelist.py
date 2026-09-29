# Vulture whitelist - false positives and intentionally-public APIs

# Dataclass field annotations (pydantic/vulture can't distinguish from variables)
ignore_names = [
    # dataclass field annotations
    "note",
    "contents",
    # module-level logger
    "log",
    # config fields (runtime-used via env/config files, not Python imports)
    "toolsets",
    "presets",
    "capabilities",
    "skills",
    "memory",
    "memory_backend",
    "memory_autosave",
    "summarization_trigger",
    "summarization_keep",
    "todos_enabled",
    "default_model",
    "mcp_servers",
    "stream",
    "stream_enabled",
    "max_tokens",
    "max_execution_time",
    "max_iterations",
    "verbose",
    "auth_token",
    "log_level",
    "backend",
    "model_config",
    "file_secret_settings",
    # pydantic-settings hooks (dynamic dispatch)
    "settings_customise_sources",
    "_read_file",
    "_validate_checkpoint_dir",
    # route handlers (FastAPI decorators, can't trace)
    "chat_stream",
    "learning_stats",
    "list_providers",
    "get_active_provider",
    "set_active_provider",
    "list_agents",
    "health",
    # @agent.tool functions (called by model at runtime)
    "assess_task_risk",
    "check_hitl_policy",
    "build_execution_plan",
    "required_tools",
    "task_confidence",
    "read_file",
    "write_file",
    "edit_file",
    "suggest_planning_hint",
    "decompose_task",
    "estimate_task_complexity",
    # ToolRegistry public API
    "to_anthropic_tool",
    "to_pydantic_model",
    "unregister",
    "by_tag",
    "by_name_glob",
    "by_risk_class",
    "filter_by_model",
    # pydantic_ai provider protocol methods
    "complete",
    "bind_capabilities"]
_total_ignore_names = len(ignore_names)
