# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

import importlib
from pathlib import Path

from jsonschema import ValidationError as JsonValidationError
from jsonschema import validate
from plugin_system.exceptions import ManifestError
from plugin_system.plugin_schema import PluginManifest
from pydantic import ValidationError as PydanticValidationError
import yaml


class ManifestValidator:
    """Validate plugin manifest."""

    def __init__(self) -> None:
        """Initialize the validator."""
        self.schema = self._load_schema()

    def _load_schema(self) -> dict:
        """Load JSON schema."""
        # Would load from file or embed
        return {}  # Placeholder

    async def validate_file(
        self, path: Path
    ) -> tuple[PluginManifest, list[str]]:
        """Validate manifest file.

        Returns:
            Tuple of (validated manifest, warnings)
        """
        warnings = []

        # Read file
        try:
            with path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            raise ManifestError(f"Failed to parse YAML: {e}")

        # Validate with Pydantic
        try:
            manifest = PluginManifest(**data)
        except PydanticValidationError as e:
            raise ManifestError(f"Invalid manifest: {e}")

        # Validate JSON schema
        try:
            validate(instance=data, schema=self.schema)
        except JsonValidationError as e:
            warnings.append(f"Schema warning: {e.message}")

        # Additional checks
        await self._validate_dependencies(manifest, warnings)
        await self._validate_entry_point(manifest, warnings)

        return manifest, warnings

    async def _validate_dependencies(
        self, manifest: PluginManifest, warnings: list[str]
    ) -> None:
        """Validate dependencies are available."""
        for dep in manifest.dependencies:
            if dep.optional:
                continue
            # Would check registry for dependency

    async def _validate_entry_point(
        self, manifest: PluginManifest, warnings: list[str]
    ) -> None:
        """Validate entry point exists."""
        module_path, class_name = manifest.entry_point.rsplit(":", 1)

        try:
            module = importlib.import_module(module_path)
            if not hasattr(module, class_name):
                warnings.append(f"Entry point class not found: {class_name}")
        except ImportError:
            warnings.append(f"Entry point module not found: {module_path}")
