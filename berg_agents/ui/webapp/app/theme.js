// Bridge so Vite picks up the canonical Berg Agents theme as a real CSS asset.
// Importing via @import url(...) inside styles.css does NOT survive bundling —
// Vite inlines the surrounding CSS but silently drops the relative @import.
// Importing from JS works reliably and is the recommended Vite pattern.

import "../../theme/theme.css";
import "./globals.css";
import "./styles.css";

