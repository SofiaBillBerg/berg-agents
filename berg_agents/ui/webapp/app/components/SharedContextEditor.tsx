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
 * along with this program.  If not, see <https://gnu.org>.
 */

/* SharedContextEditor - in-app editor for the user-owned Shared Context.
 *
 * Reads and writes the .berg-agents/context/*.md files through
 * /api/context/shared, so the user edits the SAME files the agent reads
 * every turn (and can contribute to via its tools). This is the
 * collaboration surface for the context, with each section what/why
 * history shown beside it. CodeMirror gives real Markdown editing.
 */

"use client";

import { useEffect, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { markdown } from "@codemirror/lang-markdown";
import { Streamdown } from "streamdown";
import useSWR, { mutate } from "swr";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { API_BASE } from "@/envConfig";

/** SWR key for the shared-context catalog (scopes + section list). */
const CATALOG_KEY = `${API_BASE}/api/context/shared`;

function sectionKey(name: string): string {
  return `${CATALOG_KEY}/${name}`;
}

interface HistoryEntry {
  ts: string;
  scope: string;
  section: string;
  author: string;
  why: string;
  summary: string;
}

interface CatalogSection {
  name: string;
  has_content: boolean;
}

interface CatalogData {
  scopes: Record<string, string>;
  sections: CatalogSection[];
}

interface SectionData {
  content: string;
  history: HistoryEntry[];
}

async function fetchCatalog(): Promise<CatalogData> {
  const resp = await fetch(CATALOG_KEY);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = (await resp.json()) as Partial<CatalogData>;
  return {
    scopes: data.scopes ?? {},
    sections: Array.isArray(data.sections) ? data.sections : []};
}

async function fetchSection(name: string): Promise<SectionData> {
  const resp = await fetch(sectionKey(name));
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = (await resp.json()) as Partial<SectionData>;
  return { content: data.content ?? "", history: data.history ?? [] };
}

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

  const [selected, setSelected] = useState<string | null>(null);
  const sections = catalog?.sections ?? [];
  const section = selected ?? sections[0]?.name ?? "";

  const {
    data: sectionData,
    isLoading: sectionLoading,
    error: sectionError} = useSWR<SectionData>(section ? sectionKey(section) : null, () =>
    fetchSection(section),
  );

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
    <Card>
      <CardHeader>
        <CardTitle>Shared Context</CardTitle>
        <CardDescription>
          User-owned files the agent reads every turn and can contribute to
          (with why). Project shadows global per section.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
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
              variant={section === s.name ? "default" : "secondary"}
              onPress={() => setSelected(s.name)}
            >
              {s.name}
              {s.has_content ? " •" : ""}
            </Button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">scope: {scope}</Badge>
          <Button
            size="sm"
            variant="secondary"
            onPress={() => setScope(scope === "project" ? "global" : "project")}
          >
            {scope === "project" ? "→ global" : "→ project"}
          </Button>
          <Input
            aria-label="Why (what/why discipline)"
            className="h-8 min-w-48 flex-1 text-sm"
            id="shared-context-why"
            name="shared-context-why"
            placeholder="why (the what/why discipline)"
            value={why}
            onChange={(e) => setWhy(e.target.value)}
          />
          <Button
            isDisabled={!dirty}
            size="sm"
            variant="default"
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

        <div className="flex min-h-0 flex-col gap-3 lg:flex-row">
          <div className="flex min-w-0 flex-1 flex-col rounded-lg border border-border">
            <div className="border-b border-border px-2 py-1 text-[11px] text-muted-foreground">
              Edit
            </div>
            <div className="min-h-0 flex-1">
              {sectionLoading ? (
                <p className="p-3 text-sm text-muted-foreground">Loading…</p>
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
          <div className="bg-surface-soft/30 flex min-w-0 flex-1 flex-col rounded-lg border border-border">
            <div className="border-b border-border px-2 py-1 text-[11px] text-muted-foreground">
              Preview
            </div>
            <div className="min-h-80 flex-1 overflow-y-auto p-3 text-sm leading-relaxed">
              <Streamdown>{content}</Streamdown>
            </div>
          </div>
        </div>

        {history.length > 0 && (
          <div className="flex flex-col gap-1">
            <h4 className="m-0 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
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
            <p className="text-xs text-muted-foreground">
              project: {catalog?.scopes.project ?? "…"} · global:{" "}
              {catalog?.scopes.global ?? "…"}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
export default SharedContextEditor;
