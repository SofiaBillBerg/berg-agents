"""Tests for the CodeAgents (DeepAgents) profile router."""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

import pytest

from deepagents import HarnessProfile, create_deep_agent

from berg_agents.config.settings import Settings
from berg_agents.profiles import register_profiles_from_settings
from berg_agents.profiles.router import (  # ruff: ignore[import-private-name] - testing private registry
    DEFAULT_PROFILES_CONFIG,
    _registered,
    load_profiles_from_config_file,
    register_profiles_from_config_file,
    resolve_profile,
)


def test_register_profiles_from_settings_noop_when_missing(
    monkeypatch: Any,
) -> None:
    """No profiles should be registered when settings.profiles is missing.

    This should not raise an exception.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :raises AssertionError: If any profiles were registered.
    """
    settings = Settings(profiles=None)
    monkeypatch.setattr(
        "berg_agents.profiles.router.get_settings",
        lambda: settings,
    )
    register_profiles_from_settings()


def test_register_profiles_from_settings_json(monkeypatch: Any) -> None:
    """Profiles declared as JSON should be registered.


    :param monkeypatch: The pytest-mock monkeypatch fixture.

    :raises AssertionError: If the expected profile was not registered.

    """
    captured: dict[str, HarnessProfile] = {}

    def fake_register(key: str, profile: HarnessProfile) -> None:
        """Capture the profile.

        :param key: The profile key.
        :param profile: The profile.
        :return: None
        """
        captured[key] = profile

    monkeypatch.setattr(
        "berg_agents.profiles.router.get_settings",
        lambda: Settings(
            profiles=json.dumps({
                "ollama:gpt-oss:20b": {
                    "base_system_prompt": "You are a test agent.",
                    "system_prompt_suffix": "Be brief.",
                }
            })
        ),
    )
    monkeypatch.setattr(
        "berg_agents.profiles.router.register_harness_profile",
        fake_register,
    )

    register_profiles_from_settings()

    assert "ollama:gpt-oss:20b" in captured
    profile = captured["ollama:gpt-oss:20b"]
    assert profile.base_system_prompt == "You are a test agent."
    assert profile.system_prompt_suffix == "Be brief."


def test_register_profiles_from_settings_dict(monkeypatch: Any) -> None:
    """Profiles declared as a dict should be registered.


    :param monkeypatch: The pytest-mock monkeypatch fixture.

    :raises AssertionError: If the expected profile was not registered.

    """
    captured: dict[str, HarnessProfile] = {}

    def fake_register(key: str, profile: HarnessProfile) -> None:
        """Capture the profile.

        :param key: The profile key.
        :param profile: The profile.

        """
        captured[key] = profile

    monkeypatch.setattr(
        "berg_agents.profiles.router.get_settings",
        lambda: Settings(
            profiles={
                "openai:gpt-4o": {
                    "excluded_tools": ["execute"],
                }
            }
        ),
    )
    monkeypatch.setattr(
        "berg_agents.profiles.router.register_harness_profile",
        fake_register,
    )

    register_profiles_from_settings()

    assert "openai:gpt-4o" in captured
    assert "execute" in captured["openai:gpt-4o"].excluded_tools


def test_register_profiles_from_settings_invalid_json(monkeypatch: Any) -> None:
    """Invalid JSON should raise ``ValueError``.

    :param monkeypatch: The pytest-mock monkeypatch fixture.

    :raises AssertionError: If the expected profile was not registered.

    :raises ValueError: If the JSON is invalid.

    """
    monkeypatch.setattr(
        "berg_agents.profiles.router.get_settings",
        lambda: Settings(profiles="not-json"),
    )

    with pytest.raises(ValueError, match="not valid JSON"):
        register_profiles_from_settings()


def test_register_profiles_from_settings_invalid_type(monkeypatch: Any) -> None:
    """Non-dict profile values should raise ``TypeError`` during coercion.

    :param monkeypatch: The pytest-mock monkeypatch fixture.

    :raises AssertionError: If the expected profile was not registered.

    :raises TypeError: If the profile value is not a dict or HarnessProfile.

    """
    from berg_agents.profiles.router import (
        _coerce_profile_entry,  # ruff: ignore[import-private-name]
    )

    with pytest.raises(TypeError, match="must be a dict or HarnessProfile"):
        _coerce_profile_entry(["bad"])


def test_register_profiles_from_settings_none_entry(monkeypatch: Any) -> None:
    """None entries in the profiles mapping should be skipped.

    :param monkeypatch: The pytest-mock monkeypatch fixture.

    :raises AssertionError: If the expected profile was not registered.

    """
    captured: dict[str, HarnessProfile] = {}

    def fake_register(key: str, profile: HarnessProfile) -> None:
        """Capture the profile.

        :param key: The profile key.
        :param profile: The profile.

        """
        captured[key] = profile

    monkeypatch.setattr(
        "berg_agents.profiles.router.get_settings",
        lambda: Settings(
            profiles=json.dumps({
                "ollama:gpt-oss:20b": None,
                "openai:gpt-4o": {"system_prompt_suffix": "hi"},
            })
        ),
    )
    monkeypatch.setattr(
        "berg_agents.profiles.router.register_harness_profile",
        fake_register,
    )

    register_profiles_from_settings()

    assert "ollama:gpt-oss:20b" not in captured
    assert "openai:gpt-4o" in captured


def test_default_profiles_config_path() -> None:
    """The default config path should live in the repo-root config dir.

    :raises AssertionError: If the default path is not the expected location.
    """
    assert (
        Path("/home/nvidia/WebstormProjects/berg-agents-ui/config/profiles.yaml")
        == DEFAULT_PROFILES_CONFIG
    )


def test_load_profiles_from_config_file_missing(
    tmp_path: Path,
) -> None:
    """A missing config file yields no profiles (no error).

    :param tmp_path: The pytest temporary directory fixture.
    :raises AssertionError: If any profiles were returned.
    """
    result = load_profiles_from_config_file(tmp_path / "does_not_exist.yaml")
    assert result == {}


def test_load_profiles_from_config_file_yaml(
    tmp_path: Path,
) -> None:
    """YAML profiles are parsed into HarnessProfile objects.

    :param tmp_path: The pytest temporary directory fixture.
    :raises AssertionError: If the expected profile was not parsed.
    """
    config = tmp_path / "profiles.yaml"
    config.write_text(
        '"ollama:gpt-oss:20b":\n'
        "  system_prompt_suffix: Be concise.\n"
        "  excluded_tools: [execute]\n"
        "  tool_description_overrides:\n"
        "    read_file: Read only.\n",
        encoding="utf-8",
    )

    profiles = load_profiles_from_config_file(config)
    assert "ollama:gpt-oss:20b" in profiles
    profile = profiles["ollama:gpt-oss:20b"]
    assert profile.system_prompt_suffix == "Be concise."
    assert "execute" in profile.excluded_tools
    assert profile.tool_description_overrides["read_file"] == "Read only."


def test_register_profiles_from_config_file(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """register_profiles_from_config_file registers each parsed profile.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :param tmp_path: The pytest temporary directory fixture.
    :raises AssertionError: If the expected profile was not registered.
    """
    config = tmp_path / "profiles.yaml"
    config.write_text(
        '"openai:gpt-4o":\n  system_prompt_suffix: hi\n',
        encoding="utf-8",
    )

    captured: dict[str, HarnessProfile] = {}

    def fake_register(key: str, profile: HarnessProfile) -> None:
        """Capture the profile.

        :param key: The profile key.
        :param profile: The profile.
        """
        captured[key] = profile

    monkeypatch.setattr(
        "berg_agents.profiles.router.register_harness_profile",
        fake_register,
    )

    register_profiles_from_config_file(config)

    assert "openai:gpt-4o" in captured
    assert captured["openai:gpt-4o"].system_prompt_suffix == "hi"


def test_build_berg_agents_registers_profiles_flag(
    monkeypatch: Any,
) -> None:
    """build_berg_agents registers config profiles by default, opt-out works.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :raises AssertionError: If the registration behavior is wrong.
    """
    from unittest.mock import MagicMock

    from langchain.chat_models import BaseChatModel

    from berg_agents.agents import codeagent

    calls = {"register": 0, "create": None}
    fake_llm = MagicMock(spec=BaseChatModel)

    def fake_register(path: str | Path = DEFAULT_PROFILES_CONFIG) -> None:
        """Record a registration call.

        :param path: The config path that would have been read.
        """
        calls["register"] += 1  # ty: ignore[unsupported-operator]

    def fake_create(**kwargs: Any) -> str:
        """Record the create call and return a sentinel.

        :param kwargs: Arguments forwarded to create_deep_agent.
        :return: A sentinel graph marker.
        """
        calls["create"] = kwargs  # ty: ignore[invalid-assignment]
        return "GRAPH"

    monkeypatch.setattr(
        codeagent, "register_profiles_from_config_file", fake_register
    )
    monkeypatch.setattr(codeagent, "create_deep_agent", fake_create)

    # Default: profiles are registered.
    codeagent.build_berg_agents(fake_llm)
    assert calls["register"] == 1
    assert calls["create"] is not None

    # Opt-out: no registration, but the agent is still built.
    calls["register"] = 0
    calls["create"] = None
    codeagent.build_berg_agents(fake_llm, register_profiles=False)
    assert calls["register"] == 0
    assert calls["create"] is not None


def test_resolve_profile_returns_effective_profile(monkeypatch: Any) -> None:
    """resolve_profile returns the effective merged profile for a key.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :raises AssertionError: If the resolved profile is wrong.
    """
    saved = dict(_registered)
    _registered.clear()
    try:
        monkeypatch.setattr(
            "berg_agents.profiles.router.get_settings",
            lambda: Settings(
                profiles={
                    "ollama:gpt-oss-20b": {
                        "system_prompt_suffix": "Be concise.",
                    }
                }
            ),
        )
        register_profiles_from_settings()

        profile = resolve_profile("ollama:gpt-oss-20b")
        assert profile is not None
        assert profile.system_prompt_suffix == "Be concise."
    finally:
        _registered.clear()
        _registered.update(saved)


def test_resolve_profile_unknown_key_returns_none() -> None:
    """resolve_profile returns None for keys that were never registered.

    :raises AssertionError: If an unknown key resolves to a profile.
    """
    assert resolve_profile("nope:model") is None


def test_registered_tracks_source(monkeypatch: Any, tmp_path: Path) -> None:
    """The _registered registry records where each profile came from.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :param tmp_path: The pytest temporary directory fixture.
    :raises AssertionError: If the recorded sources are wrong.
    """
    saved = dict(_registered)
    _registered.clear()
    try:
        captured: dict[str, HarnessProfile] = {}

        def fake_register(key: str, profile: HarnessProfile) -> None:
            """Capture the profile.

            :param key: The profile key.
            :param profile: The profile.
            """
            captured[key] = profile

        monkeypatch.setattr(
            "berg_agents.profiles.router.register_harness_profile",
            fake_register,
        )
        monkeypatch.setattr(
            "berg_agents.profiles.router.get_settings",
            lambda: Settings(
                profiles={"openai:gpt-4o": {"system_prompt_suffix": "hi"}}
            ),
        )

        register_profiles_from_settings()
        assert _registered["openai:gpt-4o"] == "settings"

        config = tmp_path / "profiles.yaml"
        config.write_text(
            '"ollama:gpt-oss-20b":\n  system_prompt_suffix: yo\n',
            encoding="utf-8",
        )
        register_profiles_from_config_file(config)
        assert _registered["ollama:gpt-oss-20b"] == "config-file"
    finally:
        _registered.clear()
        _registered.update(saved)
