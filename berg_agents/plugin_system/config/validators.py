"""Configuration validators for the plugin system."""

# Configuration Validation
from collections.abc import Callable
from pathlib import Path
import re
from typing import Any

# Custom Validators


class ConfigValidator:
    """Custom configuration validators."""

    def __init__(self) -> None:
        self.validators: dict[str, Callable] = {}

    def register(self, name: str, validator: Callable) -> None:
        """Register a custom validator."""
        self.validators[name] = validator

    def validate(
        self, value: Any, validator_name: str, **kwargs
    ) -> tuple[bool, str | None]:
        """Validate value with custom validator.

        Returns:
            (is_valid, error_message)
        """
        if validator_name not in self.validators:
            return True, None

        try:
            self.validators[validator_name](value, **kwargs)
            return True, None
        except ValueError as e:
            return False, str(e)


# Built-in validators
def validate_url(value: str, **kwargs) -> None:  # type: ignore[unused-argument]
    """Validate URL format."""
    from urllib.parse import urlparse

    result = urlparse(value)
    if not all([result.scheme, result.netloc]):
        raise ValueError(f"Invalid URL: {value}")


def validate_path(value: str, must_exist: bool = False, **kwargs) -> None:
    """Validate file path."""
    path = Path(value)
    if must_exist and not path.exists():
        raise ValueError(f"Path does not exist: {value}")


def validate_regex(value: str, **kwargs) -> None:
    """Validate regex pattern."""
    try:
        re.compile(value)
    except re.error as e:
        raise ValueError(f"Invalid regex: {e}")
