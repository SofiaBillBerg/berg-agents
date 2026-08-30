import React, {useEffect, useState} from "react";

/**
 * ThemeToggle component
 * Toggles between light and dark themes by setting data-berg-preset on <html>
 * Uses a visible toggle switch design
 */
function ThemeToggle() {
    const [isDark, setIsDark] = useState(false);

    // Initialize from localStorage or system preference
    useEffect(() => {
        const saved = localStorage.getItem("berg-preset");
        const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        const dark = saved ? saved === "dark" : systemDark;
        setIsDark(dark);
        document.documentElement.setAttribute("data-berg-preset", dark ? "dark" : "light");
    }, []);

    const toggle = () => {
        const next = !isDark;
        setIsDark(next);
        localStorage.setItem("berg-preset", next ? "dark" : "light");
        document.documentElement.setAttribute("data-berg-preset", next ? "dark" : "light");
    };

    return (
        <button
            onClick={toggle}
            className="theme-toggle"
            aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
            title={isDark ? "Switch to light theme" : "Switch to dark theme"}
            style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "4px",
                padding: "6px 12px",
                borderRadius: "var(--radius, 20px)",
                border: "2px solid var(--berg-border)",
                background: isDark
                    ? "linear-gradient(135deg, #2d323b, #1a1d23)"
                    : "linear-gradient(135deg, #fbf7fb, #e8e0f0)",
                color: "var(--berg-text)",
                cursor: "pointer",
                transition: "all 0.3s ease",
                boxShadow: "var(--berg-shadow-md-sm)",
                fontSize: "14px",
                fontWeight: "500",
                minWidth: "60px",
            }}
            onMouseOver={(e) => {
                e.currentTarget.style.transform = "scale(1.05)";
                e.currentTarget.style.boxShadow = "var(--berg-shadow-md)";
            }}
            onMouseOut={(e) => {
                e.currentTarget.style.transform = "scale(1)";
                e.currentTarget.style.boxShadow = "var(--berg-shadow-md-sm)";
            }}
        >
            {isDark ? (
                <>
                    <span style={{fontSize: "16px"}}>🌙</span>
                    <span style={{fontSize: "11px"}}>Dark</span>
                </>
            ) : (
                <>
                    <span style={{fontSize: "16px"}}>☀️</span>
                    <span style={{fontSize: "11px"}}>Light</span>
                </>
            )}
        </button>
    );
}

export default ThemeToggle;
