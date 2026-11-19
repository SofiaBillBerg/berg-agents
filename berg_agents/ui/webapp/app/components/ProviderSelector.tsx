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

import type { ActiveProviderState, ProviderItem } from "../actions/providers";

import { useEffect, useState } from "react";
import { Alert, ListBox, Select, Spinner } from "@heroui/react";
import useSWR, { mutate } from "swr";

import { getProviderData, switchProvider } from "../actions/providers";

/** What the providers action layer answers on a read. */
interface ProviderData {
  providers: ProviderItem[];
  active: ActiveProviderState | null;
}

/**
 * SWR key for the provider list. Null when the caller already passed the
 * data as props — then there is nothing to fetch and the fetch path
 * simply does not exist, rather than racing the props for ownership.
 */
const PROVIDERS_KEY = "berg/providers";

/**
 * Read the provider list and active selection through the actions layer
 * (secure, server-side API communication).
 *
 * @returns The providers and the active one, if any.
 * @throws When the actions layer fails — SWR then keeps the last good
 *   list, so a dropped read never empties the selector.
 */
async function fetchProviderData(): Promise<ProviderData> {
  const data = await getProviderData();
  return {
    providers: data.providers ?? [],
    active: data.active ?? null};
}

export interface ProviderSelectorProps {
  activeProvider?: ActiveProviderState | null;
  providers?: ProviderItem[];
  onSwitch?: (selected: ActiveProviderState) => void;
}

/**
 * ProviderSelector component.
 * Allows users to inspect and switch active LLM providers and models dynamically.
 * Styled with HeroUI components and Berg Agents theme tokens.
 *
 * Uses the provider actions layer for secure API communication.
 * In dev mode, this can be upgraded to true Server Actions.
 *
 * @param props - Component properties
 * @returns JSX element rendering the provider/model selector toolbar
 */
export function ProviderSelector({
  activeProvider: initialActiveProvider,
  providers: initialProviders,
  onSwitch}: ProviderSelectorProps) {
  // Props are the fast path: when the caller already passed the list AND
  // the active pair, the SWR key is null and no request is made at all.
  // Without props the shared cache is the source of truth — which also
  // means another reader of PROVIDERS_KEY sees a switch made here.
  const hasProps = Boolean(initialProviders?.length && initialActiveProvider);
  const { data: fetched, error: fetchError } = useSWR<ProviderData>(
    hasProps ? null : PROVIDERS_KEY,
    fetchProviderData,
  );

  const [isSwitching, setIsSwitching] = useState<boolean>(false);
  // The list only ever comes from props or the read; the active pair
  // additionally gets overwritten by a switch the user just made, which
  // is local state because it happens before any server re-read.
  const [switchedTo, setSwitchedTo] = useState<ActiveProviderState | null>(
    null,
  );
  const [notice, setNotice] = useState<{
    text: string;
    type: "success" | "error";
  } | null>(null);

  const providers =
    initialProviders && initialProviders.length > 0
      ? initialProviders
      : (fetched?.providers ?? []);
  const activeProvider =
    switchedTo ?? initialActiveProvider ?? fetched?.active ?? null;

  // A failed read surfaces as a notice (auto-dismissed like every other
  // one) instead of as thrown state — the selector keeps the list it has.
  const [shownFetchError, setShownFetchError] = useState<string | null>(null);
  if (fetchError && shownFetchError !== fetchError.message) {
    setShownFetchError(fetchError.message);
    setNotice({
      text: `Failed to load providers list from backend API: ${fetchError.message}`,
      type: "error"});
  }

  // Auto-dismiss status notice after 4 seconds
  useEffect(() => {
    if (notice) {
      const timer = setTimeout(() => setNotice(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [notice]);

  /**
   * Dispatches provider/model change via the actions layer.
   * The actions layer handles API communication server-side.
   *
   * @param provider - Target provider name (e.g. "ollama", "openai")
   * @param model - Target model identifier (e.g. "gpt-oss:20b", "gpt-4o")
   */
  const handleSwitch = async (provider: string, model: string) => {
    if (
      provider === activeProvider?.provider &&
      model === activeProvider?.model
    ) {
      return; // No-op if identical
    }

    setIsSwitching(true);
    try {
      // Use provider action layer for secure API switching
      const result = await switchProvider(provider, model);

      if (result.success) {
        const newState = result.active || { provider, model };
        setSwitchedTo(newState);
        // Confirm the new active pair into the shared cache so any other
        // reader of PROVIDERS_KEY (and a remount) agrees, without
        // re-fetching over the server's own answer.
        void mutate(
          PROVIDERS_KEY,
          (prev: ProviderData | undefined) =>
            prev ? { ...prev, active: newState } : prev,
          { revalidate: false },
        );
        setNotice({
          text: `Switched to ${provider} (${model})`,
          type: "success"});
        if (onSwitch) {
          onSwitch(newState);
        }
      } else {
        setNotice({
          text: `Failed to switch: ${result.error || "Unknown error"}`,
          type: "error"});
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Network error";
      setNotice({
        text: `Error switching provider: ${detail}`,
        type: "error"});
    } finally {
      setIsSwitching(false);
    }
  };

  // Key of the active provider in "provider:model" form. Null when nothing is
  // active (or the active pair is not a selectable option) so the Select
  // shows its placeholder instead of a stale value.
  // NOTE: HeroUI v3 Select is React-Aria-based - selection is controlled
  // via `selectedKey` / `onSelectionChange`, NOT `value` / `onChange`.
  const selectedValue = activeProvider
    ? `${activeProvider.provider}:${activeProvider.model}`
    : null;

  return (
    <div className="provider-selector flex items-center gap-2">
      <Select
        aria-label="Provider"
        className="provider-select text-xs max-w-72"
        isDisabled={isSwitching}
        name="provider"
        placeholder={
          providers.length === 0 ? "No providers configured" : "Select provider"
        }
        selectedKey={selectedValue}
        onSelectionChange={(key) => {
          if (key == null) return;
          const val = String(key);
          const colonIdx = val.indexOf(":");
          if (colonIdx !== -1) {
            const provider = val.substring(0, colonIdx);
            const model = val.substring(colonIdx + 1);
            void handleSwitch(provider, model);
          }
        }}
      >
        <Select.Trigger>
          <Select.Value />
          <Select.Indicator />
        </Select.Trigger>
        <Select.Popover>
          <ListBox>
            {providers.map((p, idx) => (
              <ListBox.Item
                key={`${p.name}-${p.model}-${idx}`}
                id={`${p.name}:${p.model}`}
                textValue={`${p.name} (${p.model})`}
              >
                {p.name} ({p.model})
                <ListBox.ItemIndicator />
              </ListBox.Item>
            ))}
          </ListBox>
        </Select.Popover>
      </Select>

      {isSwitching && (
        <div className="flex items-center gap-1 text-xs text-brand-purple">
          <Spinner size="sm" />
          <span>Switching...</span>
        </div>
      )}

      {notice && (
        <Alert status={notice.type === "success" ? "success" : "danger"}>
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{notice.text}</Alert.Title>
          </Alert.Content>
        </Alert>
      )}
    </div>
  );
}

export default ProviderSelector;
