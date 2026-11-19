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

/* SharedContextEditor - in-app editor for the user-owned Shared Context.
 *
 * Reads and writes the .berg-agents/context/*.md files through
 * /api/context/shared, so the user edits the SAME files the agent reads
 * every turn (and can contribute to via its tools). This is the
 * collaboration surface for the context, with each section what/why
 * history shown beside it. CodeMirror gives real Markdown editing.
 *
 * Two things this used to get wrong, both fixed by keying on the server:
 *
 *   - The section picker hardcoded six section names, a second copy of a
 *     list the backend already owns (it reports nine). The picker now
 *     renders whatever /api/context/shared returns, so a section added on
 *     the backend appears here without a code change.
 *
 *   - Switching sections fired a bare fetch with no cancellation, so two
 *     in-flight reads resolved in arrival order and a fast click could
 *     leave section A's text on screen while the button said B. SWR keys
 *     the read by section, so a late answer lands in its own entry and
 *     can never overwrite the one on screen.
 */

"use client";

import { useEffect, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { markdown } from "@codemirror/lang-markdown";
import { Button, Card, Chip } from "@heroui/react";
import { Streamdown } from "streamdown";
import useSWR, { mutate } from "swr";

import { API_BASE } from "@/envConfig";

/** SWR key for the shared-context catalog (scopes + section list). */
const CATALOG_KEY = `${API_BASE}/api/context/shared`;

/**
 * SWR key for one section's body and history. Keyed by name so each
 * section has its own cache entry — this is what makes a rapid switch
 * between sections safe: answers cannot cross over.
 *
 * @param name - The section name.
 * @returns The request URL, which doubles as the cache key.
 */
function sectionKey(name: string): string {
  return `${CATALOG_KEY}/${name}`;
}

/** One journal record from the backend history. */
interface HistoryEntry {
  ts: string;
  scope: string;
  section: string;
  author: string;
  why: string;
  summary: string;
}

/** One entry in the backend's section list. */
interface CatalogSection {
  name: string;
  has_content: boolean;
}

/** What GET /api/context/shared answers. */
interface CatalogData {
  scopes: Record<string, string>;
  sections: CatalogSection[];
}

/** What GET /api/context/shared/<name> answers. */
interface SectionData {
  content: string;
  history: HistoryEntry[];
}

/**
 * Read the shared-context catalog: which scopes exist, and every section
 * with its content flag. The section list drives the picker, so this is
 * the single source of truth for what can be edited.
 *
 * @returns The catalog.
 * @throws When the request fails.
 */
async function fetchCatalog(): Promise<CatalogData> {
  const resp = await fetch(CATALOG_KEY);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = (await resp.json()) as Partial<CatalogData>;
  return {
    scopes: data.scopes ?? {},
    sections: Array.isArray(data.sections) ? data.sections : []};
}

/**
 * Read one section's body and what/why history.
 *
 * @param name - The section name.
 * @throws When the request fails.
 */
async function fetchSection(name: string): Promise<SectionData> {
  const resp = await fetch(sectionKey(name));
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = (await resp.json()) as Partial<SectionData>;
  return { content: data.content ?? "", history: data.history ?? [] };
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

/** SharedContextEditor - view/edit the user-owned Shared Context in-app. */
export function SharedContextEditor() {
  const theme = useCodeMirrorTheme();

  const {
    data: catalog,
    isLoading: catalogLoading,
    error: catalogError} = useSWR<CatalogData>(CATALOG_KEY, fetchCatalog);

  // Which section is open. Starts unset so the first one the backend
  // reports becomes the selection — the list is the server's, not ours.
  const [selected, setSelected] = useState<string | null>(null);
  const sections = catalog?.sections ?? [];
  const section = selected ?? sections[0]?.name ?? "";

  // Revalidate on focus would rewrite the editor buffer mid-keystroke,
  // so this read is deliberately pinned: the body changes on save (which
  // mutates the key) or when the user picks another section.
  const {
    data: sectionData,
    isLoading: sectionLoading,
    error: sectionError} = useSWR<SectionData>(section ? sectionKey(section) : null, () =>
    fetchSection(section),
  );

  // The editor buffer is local — the user is typing into it — and is only
  // replaced when it belongs to a different section than the one showing.
  // Guarded in render rather than an Effect so the editor never paints
  // one section's text under another section's button.
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [bufferFor, setBufferFor] = useState<string | null>(null);
  if (sectionData !== undefined && bufferFor !== section) {
    setBufferFor(section);
    setContent(sectionData.content);
    setSaved(sectionData.content);
    setHistory(sectionData.history);
  }

  const [scope, setScope] = useState<"project" | "global">("project");
  const [why, setWhy] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  const dirty = content !== saved;

  /**
   * Save (write) or append the editor buffer to a scope, with a why.
   *
   * The PUT's own response is the editor's new truth, so the buffer is
   * adopted from it directly; the catalog and history are then
   * revalidated in the background to refresh the content dots and the
   * what/why log without blanking the editor.
   *
   * @param mode - "write" replaces the section, "append" adds a line.
   */
  const save = async (mode: "write" | "append") => {
    setStatus(null);
    try {
      const resp = await fetch(sectionKey(section), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, mode, scope, why })});
      const data = (await resp.json().catch(() => ({}))) as {
        detail?: string;
        content?: string;
        changed?: boolean;
      };
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      // Adopt the canonical text the server stored (for an append that
      // is the buffer plus the new line, which the buffer alone is not).
      const canonical = data.content || content;
      setSaved(canonical);
      setContent(canonical);
      setStatus(data.changed ? "Saved" : "No change");
      setWhy("");
      void mutate(sectionKey(section));
      void mutate(CATALOG_KEY);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Save failed");
    }
  };

  return (
    <Card variant="default">
      <Card.Header>
        <Card.Title>Shared Context</Card.Title>
        <Card.Description>
          User-owned files the agent reads every turn and can contribute to
          (with why). Project shadows global per section.
        </Card.Description>
      </Card.Header>
      <Card.Content className="flex flex-col gap-3">
        {/* Section picker; a dot marks sections that already have content.
            The list comes from the backend, so a section added there
            shows up here with no edit to this file. */}
        <div className="flex flex-wrap gap-2">
          {catalogLoading && (
            <p className="text-sm text-muted-foreground">Loading…</p>
          )}
          {catalogError && (
            <p className="text-sm text-muted-foreground">
              Sections unavailable: {catalogError.message}
            </p>
          )}
          {sections.map((s) => (
            <Button
              key={s.name}
              size="sm"
              variant={section === s.name ? "primary" : "secondary"}
              onPress={() => setSelected(s.name)}
            >
              {s.name}
              {s.has_content ? " •" : ""}
            </Button>
          ))}
        </div>

        {/* Scope, `why` (the `what`/`why` discipline), and the save controls. */}
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
            className="flex-1 min-w-48 rounded-md border border-border bg-background px-2 py-1 text-sm"
            id="shared-context-why"
            name="shared-context-why"
            placeholder="why (the what/why discipline)"
            value={why}
            onChange={(e) => setWhy(e.target.value)}
          />
          <Button
            isDisabled={!dirty}
            size="sm"
            variant="primary"
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
        {sectionError && (
          <p className="text-xs text-muted-foreground">
            {section}: {sectionError.message}
          </p>
        )}

        {/* The editor (left) and a live Streamdown preview (right) so the
            user sees rendered markdown as they type — no new route, just
            a nicer editor on the shared-context page. */}
        <div className="flex flex-col lg:flex-row gap-3 min-h-0">
          <div className="min-w-0 flex-1 flex flex-col border border-border rounded-lg">
            <div className="px-2 py-1 text-[11px] text-muted-foreground border-b border-border">
              Edit
            </div>
            <div className="min-h-0 flex-1">
              {sectionLoading ? (
                <p className="text-sm text-muted-foreground p-3">Loading…</p>
              ) : (
                <CodeMirror
                  basicSetup={{ lineNumbers: false }}
                  extensions={[markdown()]}
                  height="320px"
                  theme={theme}
                  value={content}
                  onChange={(value) => setContent(value)}
                />
              )}
            </div>
          </div>
          <div className="min-w-0 flex-1 flex flex-col border border-border rounded-lg bg-surface-soft/30">
            <div className="px-2 py-1 text-[11px] text-muted-foreground border-b border-border">
              Preview
            </div>
            <div className="min-h-80 flex-1 overflow-y-auto p-3 text-sm leading-relaxed">
              <Streamdown>{content}</Streamdown>
            </div>
          </div>
        </div>

        {/* The sections what/why history, newest first. */}
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
          project: {catalog?.scopes.project ?? "…"} · global:{" "}
          {catalog?.scopes.global ?? "…"}
        </p>
      </Card.Content>
    </Card>
  );
}

export default SharedContextEditor;
