"""Sandboxing for the plugin system."""
#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

# Sandboxing
import asyncio
from enum import Enum
import json
import logging
from feat_dev.plugin_dev.plugin_system.exceptions import PermissionDeniedError
from typing import Any
import os
import sys
from typing import Any

from feat_dev.plugin_dev.plugin_system.discovery.plugin_registry import (
    PluginError,
)
from feat_dev.plugin_dev.plugin_system.permissions.permissions import (
    Permission,
    PermissionCategory,
)

logger = logging.getLogger(__name__)


# Sandbox Levels


class SandboxLevel(str, Enum):
    """Plugin sandbox isolation levels."""

    NONE = "none"  # No sandboxing (trusted plugins)
    PROCESS = "process"  # Separate process (stdio communication)
    CONTAINER = "container"  # Docker/Podman container
    WASM = "wasm"  # WebAssembly (future)


# Process Sandbox


class ProcessSandbox:
    """Run plugin in isolated process."""

    def __init__(self, plugin_id: str, permissions: set[Permission]):
        self.plugin_id = plugin_id
        self.permissions = permissions
        self.process: asyncio.subprocess.Process | None = None

    async def start(self, entry_point: str) -> None:
        """Start sandboxed plugin process."""
        # Create restricted environment
        env = self._create_restricted_env()

        # Start process
        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "berg_agents.sandbox.runner",
            "--plugin-id",
            self.plugin_id,
            "--entry-point",
            entry_point,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        logger.info(f"Started sandbox process for {self.plugin_id}")

    def _create_restricted_env(self) -> dict[str, str]:
        """Create restricted environment variables."""
        env = {}

        # Only include allowed env vars
        for perm in self.permissions:
            if perm.category == PermissionCategory.ENV_READ:
                for var in perm.scope.get("vars", []):
                    if var in os.environ:
                        env[var] = os.environ[var]

        # Add sandbox marker
        env["BERG_SANDBOX"] = "1"
        env["BERG_PLUGIN_ID"] = self.plugin_id

        return env

    async def call(self, method: str, args: dict[str, Any]) -> Any:
        """Call plugin method via RPC."""
        if not self.process:
            raise RuntimeError("Sandbox not started")

        # Send request
        request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": args}

        self.process.stdin.write(json.dumps(request).encode() + b"\n")
        await self.process.stdin.drain()

        # Read response
        line = await self.process.stdout.readline()
        response = json.loads(line.decode())

        if "error" in response:
            raise PluginError(response["error"]["message"])

        return response.get("result")

    async def stop(self) -> None:
        """Stop sandbox process."""
        if self.process:
            self.process.terminate()
            await self.process.wait()
            logger.info(f"Stopped sandbox process for {self.plugin_id}")


# Container Sandbox (Future)


class ContainerSandbox:
    """Run plugin in Docker/Podman container."""

    def __init__(self, plugin_id: str, permissions: set[Permission]):
        self.plugin_id = plugin_id
        self.permissions = permissions
        self.container_id: str | None = None

    async def start(self, image: str) -> None:
        """Start plugin container."""
        # Build docker run command
        cmd = [
            "docker",
            "run",
            "-d",  # Detached
            "--name",
            f"berg-plugin-{self.plugin_id}",
            "--network",
            self._get_network_mode(),
            "--cpus",
            "1.0",
            "--memory",
            "512m"]

        # Add volume mounts based on permissions
        for perm in self.permissions:
            if perm.category == PermissionCategory.FILESYSTEM_READ:
                for path in perm.scope.get("paths", []):
                    cmd.extend(["-v", f"{path}:{path}:ro"])
            elif perm.category == PermissionCategory.FILESYSTEM_WRITE:
                for path in perm.scope.get("paths", []):
                    cmd.extend(["-v", f"{path}:{path}:rw"])

        cmd.append(image)

        # Start container
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        stdout, _ = await proc.communicate()
        self.container_id = stdout.decode().strip()

        logger.info(
            f"Started container {self.container_id} for {self.plugin_id}"
        )

    def _get_network_mode(self) -> str:
        """Determine network mode based on permissions."""
        has_network = any(
            p.category
            in (
                PermissionCategory.NETWORK_OUTBOUND,
                PermissionCategory.NETWORK_INBOUND,
            )
            for p in self.permissions
        )

        return "bridge" if has_network else "none"

    async def stop(self) -> None:
        """Stop and remove container."""
        if self.container_id:
            await asyncio.create_subprocess_exec(
                "docker", "stop", self.container_id
            )
            await asyncio.create_subprocess_exec(
                "docker", "rm", self.container_id
            )
            logger.info(f"Stopped container {self.container_id}")
