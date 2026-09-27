import { useEffect, useRef, useState } from "react";
import { Description, Label, ListBox } from "@heroui/react";

/**
 * SlashCommandPicker — dropdown that appears when user types "/" in the input.
 * Shows available commands with one-line descriptions and filters as you type.
 * Selecting a row (Enter via the parent's key handler, or click/tap) EXECUTES
 * the command through `onSelect` — it never fills the input for later.
 *
 * Keyboard ownership: the parent (App) owns Enter/ArrowUp/ArrowDown/Escape
 * and drives `selectedIndex` as a controlled prop, so the input's key handler
 * and this list can never double-fire on the same keypress.
 */
export interface SlashCommand {
  name: string;
  description: string;
  category: string;
}

/** Full slash-command catalog, shared with App for /help + execution. */
export const COMMANDS: SlashCommand[] = [
  {
    name: "/help",
    description: "Show all commands with what each one does",
    category: "system",
  },
  {
    name: "/agents",
    description: "List registered agents and their model tiers",
    category: "agents",
  },
  {
    name: "/models",
    description: "How to switch models (header selector)",
    category: "models",
  },
  {
    name: "/stats",
    description: "Show learning statistics from completed tasks",
    category: "stats",
  },
  {
    name: "/tools",
    description: "Where to find the available tool list",
    category: "tools",
  },
  {
    name: "/health",
    description: "System health check (status + agent count)",
    category: "system",
  },
  {
    name: "/history",
    description: "Summarize streamed events + last task result",
    category: "context",
  },
  {
    name: "/memory",
    description: "Session and long-term memory status",
    category: "context",
  },
  {
    name: "/context",
    description: "Show current event/result payload size",
    category: "context",
  },
  {
    name: "/settings",
    description: "Show active runtime config (agents + stats)",
    category: "config",
  },
  {
    name: "/skills",
    description: "List available skills",
    category: "config",
  },
  {
    name: "/mcps",
    description: "MCP server connection status",
    category: "config",
  },
  {
    name: "/export",
    description: "Download this session as a markdown file",
    category: "system",
  },
  {
    name: "/harness",
    description: "Run a task: /harness <task description>",
    category: "agents",
  },
  { name: "/task", description: "Same as /harness", category: "agents" },
  {
    name: "/clear",
    description: "Clear the input and dismiss output",
    category: "system",
  },
];

/**
 * Filter the command catalog by the text after "/".
 * Matches against both the command name and its description.
 */
export function filterCommands(filterText: string = ""): SlashCommand[] {
  const filter = (filterText ?? "").toLowerCase();
  if (!filter) return COMMANDS;
  return COMMANDS.filter(
    (c) =>
      c.name.includes(filter) || c.description.toLowerCase().includes(filter),
  );
}

export default function SlashCommandPicker({
  onSelect,
  visible,
  filterText = "",
  selectedIndex,
  onSelectedIndexChange,
}: {
  /** Called with the command name to EXECUTE (Enter/click). */
  onSelect: (cmd: string) => void;
  visible: boolean;
  filterText?: string;
  /** Highlighted row, controlled by the parent (single Enter-key owner). */
  selectedIndex: number;
  onSelectedIndexChange: (idx: number) => void;
}) {
  // Live filter text from the input (the part after "/").
  // Empty string matches every command.
  const filter = (filterText ?? "").toLowerCase();
  // Ref to the scrollable list wrapper (used to keep the highlight visible).
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = filterCommands(filterText ?? "");

  // Keys of the currently highlighted row, driving the ListBox selection.
  // Empty when the filter matches nothing so no row renders selected.
  const selectedKeys = filtered[selectedIndex]
    ? [filtered[selectedIndex].name]
    : [];

  // Reset the highlighted row whenever the filter text changes. Adjusted
  // during render (React discards this pass and re-renders immediately)
  // instead of in an effect, to avoid a synchronous setState cascade.
  const [prevFilter, setPrevFilter] = useState(filter);
  if (prevFilter !== filter) {
    setPrevFilter(filter);
    onSelectedIndexChange(0);
  }

  // Keep the highlighted row scrolled into view. Rows are queried by their
  // listbox option role so this stays correct regardless of item markup.
  useEffect(() => {
    const options = listRef.current?.querySelectorAll('[role="option"]');
    const el = options?.[selectedIndex] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  if (!visible) return null;

  return (
    <div className="slash-picker">
      <div className="slash-picker-header">
        Commands {filter && `(${filtered.length} matches)`} — Enter runs the
        highlighted command
      </div>
      <div ref={listRef} className="slash-picker-list">
        {filtered.length === 0 ? (
          <div className="slash-picker-empty">No matching commands</div>
        ) : (
          <ListBox
            aria-label="Slash commands"
            selectedKeys={selectedKeys}
            selectionMode="single"
            onAction={(key) => onSelect(String(key))}
            onSelectionChange={(keys) => {
              if (keys === "all") return;
              const first = [...keys][0];
              const idx = filtered.findIndex((c) => c.name === String(first));
              if (idx >= 0) onSelectedIndexChange(idx);
            }}
          >
            {filtered.map((cmd) => (
              <ListBox.Item
                key={cmd.name}
                id={cmd.name}
                textValue={`${cmd.name} ${cmd.description}`}
              >
                <Label className="slash-cmd-name">{cmd.name}</Label>
                <Description className="slash-cmd-desc">
                  {cmd.description}
                </Description>
                <span className="slash-cmd-cat">{cmd.category}</span>
                <ListBox.ItemIndicator />
              </ListBox.Item>
            ))}
          </ListBox>
        )}
      </div>
    </div>
  );
}
