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
 * along with this program.  If not, see <https://gnu.org>.
 */

import type { ActiveProviderState, ProviderItem } from "../actions/providers";

import { useEffect, useState } from "react";
import useSWR, { mutate } from "swr";

import { getProviderData, switchProvider } from "../actions/providers";

import { Alert, AlertTitle } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";

interface ProviderData {
  providers: ProviderItem[];
  active: ActiveProviderState | null;
}

const PROVIDERS_KEY = "berg/providers";

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

export function ProviderSelector({
  activeProvider: initialActiveProvider,
  providers: initialProviders,
  onSwitch}: ProviderSelectorProps) {
  const hasProps = Boolean(initialProviders?.length && initialActiveProvider);
  const { data: fetched, error: fetchError } = useSWR<ProviderData>(
    hasProps ? null : PROVIDERS_KEY,
    fetchProviderData,
  );

  const [isSwitching, setIsSwitching] = useState<boolean>(false);
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

  const [shownFetchError, setShownFetchError] = useState<string | null>(null);
  if (fetchError && shownFetchError !== fetchError.message) {
    setShownFetchError(fetchError.message);
    setNotice({
      text: `Failed to load providers list from backend API: ${fetchError.message}`,
      type: "error"});
  }

  useEffect(() => {
    if (notice) {
      const timer = setTimeout(() => setNotice(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [notice]);

  const handleSwitch = async (provider: string, model: string) => {
    if (
      provider === activeProvider?.provider &&
      model === activeProvider?.model
    ) {
      return;
    }

    setIsSwitching(true);
    try {
      const result = await switchProvider(provider, model);

      if (result.success) {
        const newState = result.active || { provider, model };
        setSwitchedTo(newState);
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

  const selectedValue = activeProvider
    ? `${activeProvider.provider}:${activeProvider.model}`
    : null;

  return (
    <div className="provider-selector flex items-center gap-2">
      <Select
        aria-label="Provider"
        className="provider-select max-w-72 text-xs"
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
        <SelectTrigger className="h-8 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {providers.map((p, idx) => (
            <SelectItem
              key={`${p.name}-${p.model}-${idx}`}
              id={`${p.name}:${p.model}`}
              textValue={`${p.name} (${p.model})`}
            >
              {p.name} ({p.model})
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {isSwitching && (
        <div className="text-brand-purple flex items-center gap-1 text-xs">
          <Spinner />
          <span>Switching...</span>
        </div>
      )}

      {notice && (
        <Alert
          className="px-2.5 py-1 text-xs"
          variant={notice.type === "error" ? "destructive" : "default"}
        >
          <AlertTitle className="text-xs">{notice.text}</AlertTitle>
        </Alert>
      )}
    </div>
  );
}

export default ProviderSelector;
