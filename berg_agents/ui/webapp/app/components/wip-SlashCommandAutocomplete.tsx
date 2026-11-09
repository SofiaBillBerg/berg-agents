/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
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
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://gnu.org>.
 */

"use client";

import { useState } from "react";
import {
  Autocomplete,
  EmptyState,
  ListBox,
  SearchField,
  useFilter,
  Button,
  Card} from "@heroui/react";

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
 * Auto-complete slash-command palette: a filter box plus one button per
 * matching command. Rendered by the parent only while the input
 * starts with "/". Plain HeroUI Autocomplete/ListBox - no Command primitives.
 */
export const SlashCommandAutocomplete = ({
  commands,
  onSelect}: SlashCommandAutocompleteProps) => {
  const { contains } = useFilter({ sensitivity: "base" });
  const [filter, setFilter] = useState("");

  // Rensa bort eventuellt "/" i början för sökningen
  const needle = filter.replace(/^\//, "").toLowerCase();

  const matches = commands.filter(
    (cmd) =>
      cmd.name.toLowerCase().includes(needle) ||
      cmd.description.toLowerCase().includes(needle),
  );

  return (
    <Card className="mb-2" variant="secondary">
      <Card.Content className="flex flex-col gap-1 p-2">
        <Autocomplete aria-label="Filter commands">
          <Autocomplete.Filter
            filter={contains}
            inputValue={filter}
            onInputChange={setFilter}
          >
            <SearchField>
              <SearchField.Input
                className="bg-transparent text-sm px-2 py-1 outline-none w-full"
                placeholder="Type to filter..."
              />
            </SearchField>

            <ListBox
              className="mt-1 flex flex-col gap-1 border-none p-0 shadow-none bg-transparent"
              renderEmptyState={() => (
                <EmptyState className="text-xs text-muted-foreground px-2 py-1">
                  No matching commands.
                </EmptyState>
              )}
            >
              {matches.map((cmd) => (
                <ListBox.Item
                  key={cmd.name}
                  className="p-0 border-none bg-transparent shadow-none data-[focused]:bg-transparent data-[hovered]:bg-transparent"
                  id={cmd.name}
                  textValue={cmd.name}
                >
                  <Button
                    className="justify-start w-full"
                    size="sm"
                    variant="secondary"
                    onPress={() => onSelect(cmd)}
                  >
                    <span className="font-mono">{cmd.name}</span>
                    <span className="text-muted-foreground truncate ml-2">
                      {cmd.description}
                    </span>
                  </Button>
                </ListBox.Item>
              ))}
            </ListBox>
          </Autocomplete.Filter>
        </Autocomplete>
      </Card.Content>
    </Card>
  );
};

// Backwards-compatible alias: older imports use `Command`.
export type Command = PaletteCommand;

export default SlashCommandAutocomplete;
