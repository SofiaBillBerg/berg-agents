# Plugin Security & Sandboxing Model

*Generated: 2026-10-10*

## Overview

The security model protects berg_agents from malicious or poorly-written plugins through permissions, sandboxing, auditing, and human-in-the-loop approval for sensitive operations.

## Security Principles

1. **Principle of Least Privilege** - Plugins only get permissions they explicitly request
2. **Defense in Depth** - Multiple security layers (permissions, sandboxing, HITL)
3. **Fail Secure** - Denied permissions → graceful degradation, not crashes
4. **Transparency** - All permission requests visible to users
5. **Auditability** - Complete audit log of plugin actions

## Permission System

### [Permission Categories](../permissions/permissions.py)

```python
from enum import Enum, StrEnum


class PermissionCategory(StrEnum):
    """Plugin permission categories."""

    # Filesystem
    FILESYSTEM_READ = "filesystem:read"
    FILESYSTEM_WRITE = "filesystem:write"
    FILESYSTEM_DELETE = "filesystem:delete"

    # Network
    NETWORK_OUTBOUND = "network:outbound"
    NETWORK_INBOUND = "network:inbound"

    # Environment
    ENV_READ = "env:read"
    ENV_WRITE = "env:write"

    # Process
    SUBPROCESS_SPAWN = "subprocess:spawn"
    SUBPROCESS_KILL = "subprocess:kill"

    # System
    SYSTEM_INFO = "system:info"
    SYSTEM_ADMIN = "system:admin"

    # Berg Agents
    AGENT_INVOKE = "agent:invoke"
    AGENT_MODIFY = "agent:modify"
    TOOL_REGISTER = "tool:register"
    TOOL_INVOKE = "tool:invoke"

    # Data
    DATA_READ = "data:read"
    DATA_WRITE = "data:write"
    SECRETS_READ = "secrets:read"
```

### [Permission Declaration](../permissions/permissions.py)

```yaml
# plugin.yaml
id: berg-plugin-github
version: 1.0.0

permissions:
  # Filesystem - can specify paths
  - filesystem:read
  - filesystem:write:
      paths:
        - "docs/**"
        - "README.md"
  
  # Network - can specify domains
  - network:outbound:
      domains:
        - "api.github.com"
        - "github.com"
  
  # Environment - can specify variables
  - env:read:
      vars:
        - "GITHUB_TOKEN"
        - "GITHUB_ORG"
  
  # Subprocess - can specify commands
  - subprocess:spawn:
      commands:
        - "git"
  
  # Berg agents capabilities
  - tool:register
  - tool:invoke:
      tools:
        - "read_file"
        - "write_file"
```

### [Permission Specification](../permissions/permissions.py)

```python
@dataclass
class Permission:
    """Plugin permission specification."""

    category: PermissionCategory
    scope: dict[str, Any] | None = None

    def allows(self, action: str, target: str | None = None) -> bool:
        """Check if permission allows an action."""
        # No scope = allow all
        if not self.scope:
            return True

        # Check scope-specific rules
        if self.category == PermissionCategory.FILESYSTEM_READ:
            return self._check_path_scope(target, self.scope.get("paths", []))
        elif self.category == PermissionCategory.NETWORK_OUTBOUND:
            return self._check_domain_scope(
                target, self.scope.get("domains", [])
            )
        elif self.category == PermissionCategory.ENV_READ:
            return target in self.scope.get("vars", [])
        elif self.category == PermissionCategory.SUBPROCESS_SPAWN:
            return target in self.scope.get("commands", [])

        return False

    def _check_path_scope(self, path: str, allowed_patterns: list[str]) -> bool:
        """Check if path matches allowed patterns."""
        import fnmatch
        from pathlib import Path

        path_obj = Path(path)
        return any(fnmatch.fnmatch(str(path_obj), pattern) for pattern in allowed_patterns)

    def _check_domain_scope(self, url: str, allowed_domains: list[str]) -> bool:
        """Check if URL domain is allowed."""
        from urllib.parse import urlparse

        domain = urlparse(url).netloc
        for allowed in allowed_domains:
            if domain == allowed or domain.endswith(f".{allowed}"):
                return True
        return False
```

### [Permission Checker](../permissions/permissions.py)

```python
class PermissionChecker:
    """Check plugin permissions at runtime."""

    def __init__(self, registry: PluginRegistry) -> None:
        self.registry = registry
        self.granted: dict[str, set[Permission]] = {}

    async def check(
        self,
        plugin_id: str,
        permission: PermissionCategory,
        target: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Check if plugin has permission.

        Args:
            plugin_id: Plugin requesting permission
            permission: Permission category
            target: Specific target (file path, URL, etc.)
            context: Additional context

        Returns:
            True if permission granted
        """
        entry = self.registry.get(plugin_id)
        if not entry:
            logger.error(f"Permission check for unknown plugin: {plugin_id}")
            return False

        # Check if permission was declared
        declared = any(
            p.category == permission for p in entry.metadata.permissions
        )

        if not declared:
            logger.warning(
                f"Plugin {plugin_id} requested undeclared permission: {permission}"
            )
            return False

        # Check if permission was granted
        if plugin_id not in self.granted:
            # First request - prompt user
            granted = await self._request_permission(
                plugin_id, permission, target, context
            )
            if granted:
                if plugin_id not in self.granted:
                    self.granted[plugin_id] = set()
                self.granted[plugin_id].add(
                    Permission(category=permission, scope=context)
                )
            return granted

        # Check granted permissions
        for perm in self.granted.get(plugin_id, set()):
            if perm.category == permission and perm.allows("", target):
                return True

        return False

    async def _request_permission(
        self,
        plugin_id: str,
        permission: PermissionCategory,
        target: str | None,
        context: dict[str, Any] | None,
    ) -> bool:
        """Request permission from user (HITL)."""
        # Build prompt
        prompt = f"Plugin '{plugin_id}' requests permission: {permission}"
        if target:
            prompt += f"\nTarget: {target}"
        if context:
            prompt += f"\nContext: {context}"

        # Show to user (would integrate with HITL system)
        # For now, just log
        logger.info(f"Permission request: {prompt}")

        # In real implementation, this would show a UI dialog
        # and wait for user approval
        return True  # Auto-approve for now
```

## Sandboxing

### [Sandbox Levels](../permissions/sandbox.py)

```python
class SandboxLevel(str, Enum):
    """Plugin sandbox isolation levels."""

    NONE = "none"  # No sandboxing (trusted plugins)
    PROCESS = "process"  # Separate process (stdio communication)
    CONTAINER = "container"  # Docker/Podman container
    WASM = "wasm"  # WebAssembly (future)
```

### [Process Sandbox](../permissions/sandbox.py)

```python
class ProcessSandbox:
    """Run plugin in isolated process."""

    def __init__(self, plugin_id: str, permissions: set[Permission]) -> None:
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
```

### [Container Sandbox (Future)](../permissions/sandbox.py)

```python
class ContainerSandbox:
    """Run plugin in Docker/Podman container."""

    def __init__(self, plugin_id: str, permissions: set[Permission]) -> None:
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
            in {
                PermissionCategory.NETWORK_OUTBOUND,
                PermissionCategory.NETWORK_INBOUND}
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
```

## Security Wrappers

### [Filesystem Wrapper](../permissions/security_wrappers.py)

```python
class SecureFilesystem:
    """Filesystem operations with permission checking."""

    def __init__(self, plugin_id: str, checker: PermissionChecker) -> None:
        self.plugin_id = plugin_id
        self.checker = checker

    async def read_file(self, path: str) -> str:
        """Read file with permission check."""
        if not await self.checker.check(
            self.plugin_id, PermissionCategory.FILESYSTEM_READ, target=path
        ):
            raise PermissionDeniedError(
                f"Plugin {self.plugin_id} denied read access to {path}"
            )

        # Audit log
        await self._audit("read_file", {"path": path})

        # Perform operation
        return Path(path).read_text()

    async def write_file(self, path: str, content: str) -> None:
        """Write file with permission check."""
        if not await self.checker.check(
            self.plugin_id, PermissionCategory.FILESYSTEM_WRITE, target=path
        ):
            raise PermissionDeniedError(
                f"Plugin {self.plugin_id} denied write access to {path}"
            )

        # Audit log
        await self._audit("write_file", {"path": path, "size": len(content)})

        # Perform operation
        Path(path).write_text(content)

    async def _audit(self, operation: str, details: dict[str, Any]) -> None:
        """Write to audit log."""
        logger.info(f"[AUDIT] Plugin {self.plugin_id}: {operation} {details}")
```

### [Network Wrapper](../permissions/security_wrappers.py)

```python
class SecureNetwork:
    """Network operations with permission checking."""

    def __init__(self, plugin_id: str, checker: PermissionChecker) -> None:
        self.plugin_id = plugin_id
        self.checker = checker

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """HTTP request with permission check."""
        if not await self.checker.check(
            self.plugin_id, PermissionCategory.NETWORK_OUTBOUND, target=url
        ):
            raise PermissionDeniedError(
                f"Plugin {self.plugin_id} denied network access to {url}"
            )

        # Audit log
        await self._audit("http_request", {"method": method, "url": url})

        # Perform operation
        async with httpx.AsyncClient() as client:
            return await client.request(method, url, **kwargs)

    async def _audit(self, operation: str, details: dict[str, Any]) -> None:
        """Write to audit log."""
        logger.info(f"[AUDIT] Plugin {self.plugin_id}: {operation} {details}")
```

## [Audit System](../permissionss.py)

```python
@dataclass
class AuditEntry:
    """Audit log entry."""

    timestamp: datetime
    plugin_id: str
    operation: str
    details: dict[str, Any]
    result: Literal["success", "denied", "error"]
    user_approved: bool = False


class AuditLogger:
    """Audit log for plugin actions."""

    def __init__(self, log_file: Path) -> None:
        self.log_file = log_file
        self._lock = asyncio.Lock()

    async def log(self, entry: AuditEntry) -> None:
        """Write audit entry."""
        async with self._lock:
            with self.log_file.open("a") as f:
                f.write(json.dumps(asdict(entry), default=str) + "\n")

    async def query(
        self,
        plugin_id: str | None = None,
        operation: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit log."""
        entries = []

        with self.log_file.open("r") as f:
            for line in f:
                entry_dict = json.loads(line)
                entry = AuditEntry(**entry_dict)

                # Apply filters
                if plugin_id and entry.plugin_id != plugin_id:
                    continue
                if operation and entry.operation != operation:
                    continue
                if since and entry.timestamp < since:
                    continue

                entries.append(entry)

                if len(entries) >= limit:
                    break

        return entries
```

## [HITL Integration](../permissionss.py)

```python
class PluginHITL:
    """Human-in-the-loop approval for plugins."""

    def __init__(self, hitl_manager: HITLManager) -> None:
        self.hitl_manager = hitl_manager

    async def request_approval(
        self,
        plugin_id: str,
        operation: str,
        details: dict[str, Any],
        risk_level: RiskClass = RISK_HIGH,
    ) -> bool:
        """Request user approval for operation.

        Args:
            plugin_id: Plugin requesting approval
            operation: Operation to perform
            details: Operation details
            risk_level: Risk classification

        Returns:
            True if approved
        """
        # Build approval request
        request = HITLRequest(
            agent="plugin_system",
            tool=operation,
            args=details,
            risk_level=risk_level,
            context={
                "plugin_id": plugin_id,
                "timestamp": datetime.now().isoformat()},
        )

        # Show to user and wait for approval
        approved = await self.hitl_manager.request_approval(request)

        # Audit
        logger.info(
            f"[HITL] Plugin {plugin_id} {operation}: "
            f"{'approved' if approved else 'denied'}"
        )

        return approved
```

## [Trust Levels](../permissionss.py)

```python
class TrustLevel(str, Enum):
    """Plugin trust levels."""

    UNTRUSTED = "untrusted"  # Unknown source, full sandboxing
    COMMUNITY = "community"  # Community plugin, process sandbox
    VERIFIED = "verified"  # Verified by berg_agents team
    BUILTIN = "builtin"  # Shipped with berg_agents


class TrustManager:
    """Manage plugin trust levels."""

    def __init__(self) -> None:
        self.trust_levels: dict[str, TrustLevel] = {}

    def get_trust_level(self, plugin_id: str) -> TrustLevel:
        """Get plugin trust level."""
        return self.trust_levels.get(plugin_id, TrustLevel.UNTRUSTED)

    def get_sandbox_level(self, trust: TrustLevel) -> SandboxLevel:
        """Determine sandbox level from trust."""
        if trust in (TrustLevel.BUILTIN, TrustLevel.VERIFIED):
            return SandboxLevel.NONE
        elif trust == TrustLevel.COMMUNITY:
            return SandboxLevel.PROCESS
        else:
            return SandboxLevel.CONTAINER
```

## Configuration

```yaml
# .berg-agents/bergagents.yaml
plugins:
  security:
    # Default sandbox level
    default_sandbox: "process"
    
    # Auto-approve permissions for trusted plugins
    auto_approve_trusted: true
    
    # Audit log location
    audit_log: "logs/plugin-audit.jsonl"
    
    # Permission timeout (seconds)
    permission_timeout: 300
    
    # Trust levels
    trust:
      berg-plugin-github: "verified"
      my-local-plugin: "community"
```

## Summary

**Permission system:** Declare, check, grant, audit

**Sandboxing:** Process isolation, container isolation (future)

**Security layers:** Permissions → Sandboxing → HITL → Audit

**Key features:**
- Fine-grained permissions with scopes
- Runtime permission checking
- Process/container sandboxing
- Complete audit trail
- HITL for sensitive operations
- Trust-based security policies

**Next:** Configuration and settings system
