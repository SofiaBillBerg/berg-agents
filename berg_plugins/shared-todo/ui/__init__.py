"""Shared ToDo plugin — UI assets and manifest.

This package owns its interface: the React component that renders the
collaborative todo list lives in `berg_plugins/shared-todo/ui/`, and
`plugin.yaml` declares it under `ui:`. The host (berg-agents) only
provides a mount point and the plugin API — it never imports or knows
about todo types.
"""
