# Shared ToDo plugin UI

This file lives inside the plugin package (`berg_plugins/shared-todo/ui/`)
so the plugin owns its own interface — the host only provides the mount
point and the API surface.
The host's job is to discover *that* this
plugin has a surface (via the `ui:` block in `plugin.yaml`), then render
it — it never knows what "todos" are.

Contents:

- `README.md` — this file, the contract between plugin and host.
- `TodoSurface.tsx` — the component the host mounts.
- `registry.ts` — mapping plugin id → component for the host build.

The host's `PluginUIRegistry` resolves the plugin id it gets from
`GET /api/plugins` against this mapping, so installing another plugin
means shipping its own `ui/` dir plus one registry entry — never a
change to the host app (no `TodoPanel` import in `App.tsx`).
"""
