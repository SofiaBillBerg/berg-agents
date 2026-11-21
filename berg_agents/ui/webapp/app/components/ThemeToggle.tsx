/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 *
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

import { useEffect, useState } from "react";
import { RiMoonLine, RiSunLine } from "@remixicon/react";

import { Switch } from "@/components/ui/switch.tsx";

/**
 * ThemeToggle component.
 * Toggles between light and dark themes by switching the `.dark` class and
 * the `data-theme` attribute on <html> - the selectors read (see app/globals.css: `.dark, [data-theme="dark"]`).
 * Persisted under the `berg-theme` key, falling back to the legacy
 * `berg-preset` key so existing visitors keep their choice.
 */

/** Storage keys for the theme preference (new key first, legacy fallback). */
const THEME_KEY = "berg-theme";
const LEGACY_KEY = "berg-preset";

/**
 * Apply the theme to <html>: `.dark` class plus `data-theme`, keeping the
 * legacy `data-berg-preset` attribute in sync for any custom CSS that reads
 * it. Single place so initial paint, effect sync, and click all agree.
 */
function applyTheme(isDark: boolean) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.toggle("dark", isDark);
  root.setAttribute("data-theme", isDark ? "dark" : "light");
  root.setAttribute("data-berg-preset", isDark ? "dark" : "light");
}

/**
 * Read the initial theme before first render (stored value wins, otherwise
 * the OS preference). Runs as a useState initializer so no mount effect
 * needs to setState after the fact.
 */
function readInitialDark() {
  if (typeof window === "undefined") return false;
  const saved =
    localStorage.getItem(THEME_KEY) ?? localStorage.getItem(LEGACY_KEY);
  if (saved) return saved === "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function ThemeToggle() {
  const [isDark, setIsDark] = useState(readInitialDark);

  // Sync the external DOM theme from state; never setState here.
  useEffect(() => {
    applyTheme(isDark);
  }, [isDark]);

  const toggle = () => {
    const next = !isDark;
    setIsDark(next);
    try {
      localStorage.setItem(THEME_KEY, next ? "dark" : "light");
    } catch {
      // Private-mode storage may throw - the in-memory state still applies.
    }
    applyTheme(next);
  };

  // Themed Switch, not a bespoke pill: this used to be a hand-styled
  // gradient button with its own CSS variables — one more surface the
  // theme tokens did not reach. Sun and moon flank a small switch, so the
  // control is a third the width and the same component as every other
  // boolean in the app.
  return (
    <div
      className="group inline-flex items-center gap-1"
      data-state={isDark ? "checked" : "unchecked"}
      title="Toggle between dark and light theme"
    >
      <RiSunLine
        aria-hidden="true"
        className="size-3.5 opacity-70 transition-opacity group-data-[state=checked]:opacity-40"
      />
      <Switch
        aria-label="Toggle between dark and light theme"
        isSelected={isDark}
        size="sm"
        onChange={toggle}
      />
      <RiMoonLine
        aria-hidden="true"
        className="size-3.5 opacity-70 transition-opacity group-data-[state=unchecked]:opacity-40"
      />
    </div>
  );
}

export default ThemeToggle;
