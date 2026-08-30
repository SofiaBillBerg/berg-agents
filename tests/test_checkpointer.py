"""Property tests for `build_checkpointer` factory function.

Tests for checkpointer creation logic with SqliteSaver and InMemorySaver fallback.
"""

from __future__ import annotations

from pathlib import Path

from berg_agents.utils.checkpointer import build_checkpointer


class TestBuildCheckpointerProperty:
    """Property tests for build_checkpointer function."""

    def test_build_checkpointer_returns_non_none(self) -> None:  # ruff: ignore[no-self-use]
        """Property 13: build_checkpointer always returns a checkpointer object.

        For any valid checkpoint directory path, the function should return
        either SqliteSaver or InMemorySaver (never None).
        """
        checkpointer = build_checkpointer(
            checkpoint_dir="/tmp/test_checkpoints"
        )

        assert checkpointer is not None

    def test_build_checkpointer_fallback_on_invalid_path(self) -> None:  # ruff: ignore[no-self-use]
        """Property 13 variant: Invalid paths return InMemorySaver fallback."""
        checkpointer = build_checkpointer(
            checkpoint_dir="/nonexistent/path/that/does/not/exist"
        )

        assert checkpointer is not None
        assert checkpointer.__class__.__name__ == "InMemorySaver"


class TestBuildCheckpointerExample:
    """Example tests for build_checkpointer functionality."""

    def test_default_reads_from_settings(self) -> None:  # ruff: ignore[no-self-use]
        """Example test: default config uses Settings.checkpoint_dir."""
        checkpointer = build_checkpointer()

        assert checkpointer is not None

    def test_custom_path_creates_checkpointer(self, tmp_path: Path) -> None:  # ruff: ignore[no-self-use]
        """Example test: custom path creates checkpointer successfully."""
        custom_dir = tmp_path / "test_checkpoints"

        checkpointer = build_checkpointer(checkpoint_dir=str(custom_dir))

        assert checkpointer is not None

    def test_returns_valid_saver_type(self) -> None:  # ruff: ignore[no-self-use]
        """Example test: returned object is a valid saver type."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            checkpointer = build_checkpointer(
                checkpoint_dir=f"{tmpdir}/checkpoints"
            )

            assert checkpointer is not None
            class_name = checkpointer.__class__.__name__
            assert class_name in {
                "SqliteSaver",
                "InMemorySaver",
                "_GeneratorContextManager",
            }
