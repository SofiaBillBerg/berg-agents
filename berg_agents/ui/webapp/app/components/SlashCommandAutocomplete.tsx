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

"use client";
import { useFilter } from "react-aria-components";
import * as React from "react";
import { RiTerminalBoxLine, RiToolsLine } from "@remixicon/react";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList} from "@/components/ui/command";

export interface SlashCommandItem {
  name: string;
  description: string;
}

interface SlashCommandPaletteProps {
  commands: SlashCommandItem[];
  query: string;
  onSelect: (command: SlashCommandItem) => void;
  onClose: () => void;
}

const SYSTEM_COMMANDS = new Set([
  "/help",
  "/agents",
  "/stats",
  "/clear",
  "/memory",
  "/skills",
  "/mcps",
  "/exit"]);

export function SlashCommandPalette({
  commands,
  query,
  onSelect,
  onClose}: SlashCommandPaletteProps) {
  const { contains } = useFilter({ sensitivity: "base" });

  const systemCommands = React.useMemo(
    () => commands.filter((c) => SYSTEM_COMMANDS.has(c.name)),
    [commands],
  );
  const toolCommands = React.useMemo(
    () => commands.filter((c) => !SYSTEM_COMMANDS.has(c.name)),
    [commands],
  );

  // Sync search state with the chat box input (strip leading "/")
  const search = query.replace(/^\//, "");

  return (
    <div
      className="mb-1.5 shrink-0 rounded-lg border bg-popover text-popover-foreground shadow-md"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}
    >
      <Command
        filter={(textValue, inputValue) => contains(textValue, inputValue)}
        inputValue={search}
        onInputChange={() => {
          // Search is driven directly from the chat InputBar
        }}
      >
        <CommandInput placeholder="Filter slash commands…" />
        <CommandList className="max-h-56">
          <CommandEmpty>No matching commands.</CommandEmpty>

          {systemCommands.length > 0 && (
            <CommandGroup heading="System">
              {systemCommands.map((cmd) => (
                <CommandItem
                  key={cmd.name}
                  id={cmd.name}
                  textValue={`${cmd.name} ${cmd.description}`}
                  onAction={() => onSelect(cmd)}
                >
                  <RiTerminalBoxLine className="size-3.5 shrink-0 text-primary" />
                  <span className="font-mono text-xs font-semibold">
                    {cmd.name}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    {cmd.description}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}

          {toolCommands.length > 0 && (
            <CommandGroup heading="Agent Tools">
              {toolCommands.map((cmd) => (
                <CommandItem
                  key={cmd.name}
                  id={cmd.name}
                  textValue={`${cmd.name} ${cmd.description}`}
                  onAction={() => onSelect(cmd)}
                >
                  <RiToolsLine className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="font-mono text-xs font-semibold">
                    {cmd.name}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    {cmd.description}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
        </CommandList>
      </Command>
    </div>
  );
}
