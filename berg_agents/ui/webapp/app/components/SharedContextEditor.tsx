/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
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

/* SharedContextEditor - in-app editor for the human-owned Shared Context.
 *
 * Reads and writes the .berg-agents/context/*.md files through
 * /api/context/shared, so the human edits the SAME files the agent reads
 * every turn (and can contribute to via its tools). This is the
 * collaboration surface for the context, with each section what/why
 * history shown beside it. CodeMirror gives real Markdown editing.
 */

"use client";

import {useCallback, useEffect, useState} from "react";
import CodeMirror from "@uiw/react-codemirror";
import {markdown} from "@codemirror/lang-markdown";
import {Button, Card, Chip} from "@heroui/react";

import {API_BASE} from "@/envConfig";

/** Canonical context sections (mirror of SECTIONS on the backend). */
const SECTIONS = [
    "preferences",
    "project",
    "task-state",
    "files",
    "notes",
    "learnings"] as const;

/** One journal record from the backend history. */
interface HistoryEntry {
    ts: string;
    scope: string;
    section: string;
    author: string;
    why: string;
    summary: string;
}

/** Follow the app's light/dark theme so CodeMirror matches. */
function useCodeMirrorTheme(): "light" | "dark" {
    const [theme, setTheme] = useState<"light" | "dark">("dark");
    useEffect(() => {
        const apply = () =>
            setTheme(
                document.documentElement.classList.contains("dark") ? "dark" : "light",
            );
        apply();
        const observer = new MutationObserver(apply);
        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ["class"]});
        return () => observer.disconnect();
    }, []);
    return theme;
}

/** SharedContextEditor - view/edit the human-owned Shared Context in-app. */
export function SharedContextEditor() {
    const theme = useCodeMirrorTheme();
    const [sections, setSections] = useState<
        Array<{ name: string; has_content: boolean }>
    >([]);
    const [scopes, setScopes] = useState<Record<string, string>>({});
    const [section, setSection] = useState<string>(SECTIONS[0]);
    const [content, setContent] = useState("");
    const [saved, setSaved] = useState("");
    const [scope, setScope] = useState<"project" | "global">("project");
    const [why, setWhy] = useState("");
    const [history, setHistory] = useState<HistoryEntry[]>([]);
    const [status, setStatus] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);

    const loadCatalog = useCallback(async () => {
        try {
            const resp = await fetch(`${API_BASE}/api/context/shared`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            setScopes(data.scopes || {});
            setSections(data.sections || []);
        } catch (e) {
            setStatus(`Catalog: ${e instanceof Error ? e.message : e}`);
        }
    }, []);

    const loadSection = useCallback(async (name: string) => {
        setLoading(true);
        try {
            const resp = await fetch(`${API_BASE}/api/context/shared/${name}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            setContent(data.content || "");
            setSaved(data.content || "");
            setHistory(data.history || []);
        } catch (e) {
            setStatus(`${name}: ${e instanceof Error ? e.message : e}`);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void loadCatalog();
    }, [loadCatalog]);

    useEffect(() => {
        void loadSection(section);
    }, [section, loadSection]);

    const dirty = content !== saved;

    /** Save (write) or append the editor buffer to a scope, with a why. */
    const save = async (mode: "write" | "append") => {
        setStatus(null);
        try {
            const resp = await fetch(`${API_BASE}/api/context/shared/${section}`, {
                method: "PUT",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({content, mode, scope, why})});
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
            setSaved(data.content || content);
            setStatus(data.changed ? "Saved" : "No change");
            setWhy("");
            void loadCatalog();
            void loadSection(section);
        } catch (e) {
            setStatus(e instanceof Error ? e.message : "Save failed");
        }
    };

    return (
        <Card variant="default">
            <Card.Header>
                <Card.Title>Shared Context</Card.Title>
                <Card.Description>
                    Human-owned files the agent reads every turn and can contribute to
                    (with why). Project shadows global per section.
                </Card.Description>
            </Card.Header>
            <Card.Content className="flex flex-col gap-3">
                {/* Section picker; a dot marks sections that already have content. */}
                <div className="flex flex-wrap gap-2">
                    {SECTIONS.map((name) => {
                        const has = sections.find((s) => s.name === name)?.has_content;
                        return (
                            <Button
                                key={name}
                                size="sm"
                                variant={section === name ? "primary" : "secondary"}
                                onPress={() => setSection(name)}
                            >
                                {name}
                                {has ? " •" : ""}
                            </Button>
                        );
                    })}
                </div>

                {/* Scope, why (the what/why discipline), and the save controls. */}
                <div className="flex flex-wrap items-center gap-2">
                    <Chip size="sm" variant="soft">
                        scope: {scope}
                    </Chip>
                    <Button
                        size="sm"
                        variant="secondary"
                        onPress={() => setScope(scope === "project" ? "global" : "project")}
                    >
                        {scope === "project" ? "→ global" : "→ project"}
                    </Button>
                    <input
                        aria-label="Why (what/why discipline)"
                        name="shared-context-why"
                        id="shared-context-why"
                        className="flex-1 min-w-[12rem] rounded-md border border-border bg-background px-2 py-1 text-sm"
                        placeholder="why (the what/why discipline)"
                        value={why}
                        onChange={(e) => setWhy(e.target.value)}
                    />
                    <Button
                        size="sm"
                        variant="primary"
                        isDisabled={!dirty}
                        onPress={() => void save("write")}
                    >
                        Save
                    </Button>
                    <Button
                        size="sm"
                        variant="secondary"
                        onPress={() => void save("append")}
                    >
                        Append line
                    </Button>
                </div>

                {status && <p className="text-xs text-muted-foreground">{status}</p>}

                {/* The editor itself. */}
                {loading ? (
                    <p className="text-sm text-muted-foreground">Loading…</p>
                ) : (
                    <CodeMirror
                        value={content}
                        height="320px"
                        theme={theme}
                        extensions={[markdown()]}
                        onChange={(value) => setContent(value)}
                        basicSetup={{lineNumbers: false}}
                    />
                )}

                {/* The section's what/why history, newest first. */}
                {history.length > 0 && (
                    <div className="flex flex-col gap-1">
                        <h4 className="m-0 text-xs font-semibold uppercase tracking-wider text-muted">
                            History (what / why)
                        </h4>
                        <ul className="flex list-none flex-col gap-0.5 p-0 text-[11px] text-muted-foreground">
                            {history.slice(0, 8).map((h, i) => (
                                <li key={`${h.ts}-${i}`}>
                                    {h.ts.slice(0, 19)} · {h.scope} · {h.author} ·{" "}
                                    {h.why || h.summary}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}

                <p className="text-[11px] text-muted-foreground">
                    project: {scopes.project ?? "…"} · global: {scopes.global ?? "…"}
                </p>
            </Card.Content>
        </Card>
    );
}

export default SharedContextEditor;
