

"use client";

import {useState} from "react";
import {Button, Card} from "@heroui/react";

export interface PaletteCommand {
  name: string;
  description: string;
}

interface SlashCommandAutocompleteProps {
  /** Commands to offer (e.g. [{name: '/help', description: '...'}]) */
  commands: PaletteCommand[];
  /** Called with the chosen command */
  onSelect: (command: PaletteCommand) => void;
}

/**
 * Minimal slash-command palette: a filter box plus one button per
 * matching command. Rendered by the parent only while the input
 * starts with "/". Plain HeroUI Button/Card - no Command primitives.
 */
export const SlashCommandAutocomplete = ({
  commands,
  onSelect}: SlashCommandAutocompleteProps) => {
  const [filter, setFilter] = useState("");

  const needle = filter.replace(/^\//, "").toLowerCase();
  const matches = commands.filter(
    (cmd) =>
      cmd.name.toLowerCase().includes(needle) ||
      cmd.description.toLowerCase().includes(needle),
  );

  return (
    <Card className="mb-2" variant="secondary">
      <Card.Content className="flex flex-col gap-1 p-2">
        <input
          aria-label="Filter commands"
          className="bg-transparent text-sm px-2 py-1 outline-none"
          placeholder="Type to filter..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        {matches.length === 0 && (
          <span className="text-xs text-muted-foreground px-2">
            No matching commands.
          </span>
        )}
        {matches.map((cmd) => (
          <Button
            key={cmd.name}
            className="justify-start"
            size="sm"
            variant="secondary"
            onPress={() => onSelect(cmd)}
          >
            <span className="font-mono">{cmd.name}</span>
            <span className="text-muted-foreground truncate">
              {cmd.description}
            </span>
          </Button>
        ))}
      </Card.Content>
    </Card>
  );
};

// Backwards-compatible alias: older imports use `Command`.
export type Command = PaletteCommand;

export default SlashCommandAutocomplete;
