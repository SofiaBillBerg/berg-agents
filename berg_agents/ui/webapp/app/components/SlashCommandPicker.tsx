import React, {useEffect, useRef, useState} from "react";

/**
 * SlashCommandPicker — dropdown that appears when user types "/" in the input.
 * Shows available commands with descriptions. On select, fills the input.
 */
export default function SlashCommandPicker({onSelect, visible}) {
    const [selectedIndex, setSelectedIndex] = useState(0);
    const [filter, setFilter] = useState("");
    const listRef = useRef(null);

    const commands = [
        {name: "/help", description: "Show available commands", category: "system"},
        {name: "/agents", description: "List registered agents", category: "agents"},
        {name: "/models", description: "Show available models", category: "models"},
        {name: "/stats", description: "Learning statistics", category: "stats"},
        {name: "/tools", description: "List available tools", category: "tools"},
        {name: "/health", description: "System health check", category: "system"},
        {name: "/history", description: "Show conversation history", category: "context"},
        {name: "/memory", description: "Memory information", category: "context"},
        {name: "/context", description: "Show current context", category: "context"},
        {name: "/settings", description: "Show settings", category: "config"},
        {name: "/plugins", description: "List plugins", category: "config"},
        {name: "/skills", description: "List skills", category: "config"},
        {name: "/mcps", description: "MCP server status", category: "config"},
        {name: "/orchestrate", description: "Run task through orchestrator", category: "agents"},
        {name: "/task", description: "Same as /orchestrate", category: "agents"},
        {name: "/clear", description: "Clear conversation", category: "system"},
    ];

    const filtered = commands.filter(
        (c) =>
            c.name.includes(filter.toLowerCase()) ||
            c.description.toLowerCase().includes(filter.toLowerCase())
    );

    useEffect(() => {
        setSelectedIndex(0);
    }, [filter]);

    useEffect(() => {
        if (!visible) return;
        const handleKey = (e) => {
            if (e.key === "ArrowDown") {
                e.preventDefault();
                setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSelectedIndex((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter" && filtered[selectedIndex]) {
                e.preventDefault();
                onSelect(filtered[selectedIndex].name);
            }
        };
        window.addEventListener("keydown", handleKey);
        return () => window.removeEventListener("keydown", handleKey);
    }, [visible, filtered, selectedIndex, onSelect]);

    useEffect(() => {
        if (listRef.current) {
            const el = listRef.current.children[selectedIndex];
            if (el) el.scrollIntoView({block: "nearest"});
        }
    }, [selectedIndex]);

    if (!visible) return null;

    return (
        <div className="slash-picker">
            <div className="slash-picker-header">
                Commands {filter && `(${filtered.length} matches)`}
            </div>
            <div className="slash-picker-list" ref={listRef}>
                {filtered.length === 0 && (
                    <div className="slash-picker-empty">No matching commands</div>
                )}
                {filtered.map((cmd, i) => (
                    <div
                        key={cmd.name}
                        className={`slash-picker-item ${i === selectedIndex ? "selected" : ""}`}
                        onClick={() => onSelect(cmd.name)}
                        onMouseEnter={() => setSelectedIndex(i)}
                    >
                        <span className="slash-cmd-name">{cmd.name}</span>
                        <span className="slash-cmd-desc">{cmd.description}</span>
                        <span className="slash-cmd-cat">{cmd.category}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}
