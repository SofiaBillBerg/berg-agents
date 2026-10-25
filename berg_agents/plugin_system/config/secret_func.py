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

"""Secret management for the plugin system."""

# Secrets Management

from pathlib import Path
import re
from typing import Any

# Secret Detection
from cryptography.fernet import Fernet


class SecretDetector:
    """Detect and protect secrets in configuration."""

    SECRET_PATTERNS = [
        r"token",
        r"api[_-]?key",
        r"password",
        r"secret",
        r"private[_-]?key",
        r"credential"]

    def is_secret_field(self, field_name: str) -> bool:
        """Check if field name suggests a secret."""
        field_lower = field_name.lower()
        return any(
            re.search(pattern, field_lower) for pattern in self.SECRET_PATTERNS
        )

    def mark_secrets(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Mark secret fields in schema."""
        if "properties" not in schema:
            return schema

        for field, field_schema in schema["properties"].items():
            if self.is_secret_field(field):
                field_schema["secret"] = True

        return schema


# Secret Storage


class SecretStore:
    """Encrypted storage for plugin secrets."""

    def __init__(self, key_file: Path) -> None:
        self.key_file = key_file
        self._cipher = self._load_or_create_key()

    def _load_or_create_key(self) -> Fernet:
        """Load or create encryption key."""
        if self.key_file.exists():
            key = self.key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            self.key_file.write_bytes(key)
            self.key_file.chmod(0o600)  # Owner read/write only

        return Fernet(key)

    def encrypt(self, value: str) -> str:
        """Encrypt a secret value."""
        encrypted = self._cipher.encrypt(value.encode())
        return encrypted.decode()

    def decrypt(self, encrypted_value: str) -> str:
        """Decrypt a secret value."""
        decrypted = self._cipher.decrypt(encrypted_value.encode())
        return decrypted.decode()

    async def store_secret(self, plugin_id: str, key: str, value: str) -> None:
        """Store an encrypted secret."""
        self.encrypt(value)
        # Store in secure location (e.g., keyring, vault)

    async def retrieve_secret(self, plugin_id: str, key: str) -> str | None:
        """Retrieve and decrypt a secret."""
        # Retrieve from secure location
        encrypted: None = None  # TODO: Implement retrieval logic
        if encrypted:
            return self.decrypt(encrypted)
        return None
