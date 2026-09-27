# Berg Agents — UI theme

This directory is the single source of truth for the visual style of every
surface berg_agents ships: web UI, TUI, and (via `docs/`) the documentation.

```
berg_agents/ui/theme/
├── README.md          ← you are here
├── tokens/
│   ├── colors.css     ← palette as CSS custom properties
│   ├── typography.css ← font stacks, sizes, weights
│   ├── spacing.css    ← spacing scale
│   └── colors.py      ← same palette as a Python dict (CLI + server)
├── components/
│   ├── base.css       ← buttons, cards, inputs, layout primitives
│   └── banner.css     ← the signature purple→blue→teal title banner
├── presets/
│   ├── light.css      ← default
│   └── dark.css       ← opt-in
├── theme.css          ← single @import aggregator for the webapp
└── sync.py            ← regenerates docs/styles/* from the canonical files
```

## Why this exists

The docs site (Quarto) already has its own `docs/styles/custom.css` that
defines a "SofiaBillBerg" style — purple→blue→teal gradient, Inter on a
near-white background, soft borders. Without a shared module the webapp
ends up looking like a generic Google-blue product and we end up with
two copies of the same palette drifting apart.

By making `berg_agents/ui/theme/` canonical, the docs site imports from
it (via `sync.py` regenerating symlinks or copies into `docs/styles/`),
the webapp imports `theme.css` directly, and the CLI/server import
`tokens/colors.py`. One palette, one source, no drift.

## Usage

Webapp — in `styles.css` replace the current `var(--color-*)` block with:

```css
@import './theme/theme.css';
```

CLI/server:

```python
from berg_agents.ui.theme.tokens.colors import PRIMARY_GRADIENT, BG
```

## Syncing to docs

After editing any file in `tokens/` or `components/`:

```bash
python -m berg_agents.ui.theme.sync
```

This regenerates `docs/styles/custom.css` and `docs/styles/extra.css` from
the canonical sources.
