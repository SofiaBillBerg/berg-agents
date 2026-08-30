"""Berg Agents colour palette — Python mirror of tokens/colors.css.

Single source of truth for the palette lives in `tokens/colors.css`. This
module exposes the same values so the CLI and the FastAPI server can
render with the same colours the webapp and the docs use.

Keep in sync manually after editing colors.css, or run:

    python -m berg_agents.ui.theme.sync --check
"""

from __future__ import annotations


# Brand — the signature gradient stops
BRAND_PURPLE = "#7d029c"
BRAND_BLUE = "#3b528b"
BRAND_TEAL = "#21908c"

# Accent variants
ACCENT_ORCHID = "#e841c7"
ACCENT_MAGENTA = "#8603a6"
ACCENT_MAUVE = "#440154"
ACCENT_DEEP = "#1640ab"
ACCENT_CORNFLOWER = "#3c66d1"
ACCENT_YELLOW = "#fde725"
ACCENT_AMBER = "#fd9f07"

# Neutrals
TEXT = "#010a13"
BG = "#fbf7fb"
SURFACE = "#fffafa"
SURFACE_TINT = "#f1f3f4"
SURFACE_SOFT = "rgba(248, 237, 248, 0.76)"
BORDER = "#e9ecef"
MUTED = "#551a8b"

# Status
STATUS_INFO = "#3b528b"
STATUS_SUCCESS = "#21908c"
STATUS_WARN = "#fd9f07"
STATUS_ERROR = "#d73027"

# Code
CODE_BG = "rgba(248, 237, 248, 0.76)"
CODE_TEXT = "#551a8b"

# Gradients
GRADIENT_BRAND = f"linear-gradient(135deg, {BRAND_PURPLE} 0%, {BRAND_BLUE} 50%, {BRAND_TEAL} 100%)"
GRADIENT_SOFT = "linear-gradient(135deg, #3358b5, #f285d5)"


# Grouped export so callers can `from ... import PALETTE` and use `PALETTE['brand_purple']`
PALETTE: dict[str, str] = {
    "brand_purple": BRAND_PURPLE,
    "brand_blue": BRAND_BLUE,
    "brand_teal": BRAND_TEAL,
    "accent_orchid": ACCENT_ORCHID,
    "accent_magenta": ACCENT_MAGENTA,
    "accent_mauve": ACCENT_MAUVE,
    "accent_deep": ACCENT_DEEP,
    "accent_cornflower": ACCENT_CORNFLOWER,
    "accent_yellow": ACCENT_YELLOW,
    "accent_amber": ACCENT_AMBER,
    "text": TEXT,
    "bg": BG,
    "surface": SURFACE,
    "surface_tint": SURFACE_TINT,
    "border": BORDER,
    "muted": MUTED,
    "status_info": STATUS_INFO,
    "status_success": STATUS_SUCCESS,
    "status_warn": STATUS_WARN,
    "status_error": STATUS_ERROR,
    "code_bg": CODE_BG,
    "code_text": CODE_TEXT,
    "gradient_brand": GRADIENT_BRAND,
    "gradient_soft": GRADIENT_SOFT,
}
