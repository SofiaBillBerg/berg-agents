import {useEffect, useState} from "react";

/**
 * ThemeToggle component.
 * Toggles between light and dark themes by switching the `.dark` class and
 * the `data-theme` attribute on <html> - the selectors HeroUI v3 actually
 * reads (see app/globals.css: `.dark, [data-theme="dark"]`).
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

  return (
    <button
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className={`theme-toggle flex items-center justify-center gap-1 px-3 py-1.5 rounded-full border-2 border-[var(--berg-border)] text-[var(--berg-text)] cursor-pointer transition-all duration-300 shadow-sm text-sm font-medium min-w-[60px] hover:scale-105 hover:shadow-md ${
        isDark
          ? "bg-gradient-to-br from-[#2d323b] to-[#1a1d23]"
          : "bg-gradient-to-br from-[#f8edf8] to-[#e8e0f0]"
      }`}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={toggle}
    >
      {isDark ? (
        <>
          <span className="text-base">🌙</span>
          <span className="text-[11px]">Dark</span>
        </>
      ) : (
        <>
          <span className="text-base">☀️</span>
          <span className="text-[11px]">Light</span>
        </>
      )}
    </button>
  );
}

export default ThemeToggle;
