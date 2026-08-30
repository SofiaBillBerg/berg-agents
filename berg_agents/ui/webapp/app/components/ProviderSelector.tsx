import React, { useCallback, useEffect, useState } from "react";
import { Chip, Spinner } from "@heroui/react";
import { apiFetch } from "@/envConfig.ts";

export interface ProviderItem {
  name: string;
  model: string;
}

export interface ActiveProviderState {
  provider: string;
  model: string;
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
 * @param props - Component properties
 * @returns JSX element rendering the provider/model selector toolbar
 */
export function ProviderSelector({
  activeProvider: initialActiveProvider,
  providers: initialProviders,
  onSwitch,
}: ProviderSelectorProps) {
  const [providers, setProviders] = useState<ProviderItem[]>(
    initialProviders || [],
  );
  const [activeProvider, setActiveProvider] =
    useState<ActiveProviderState | null>(initialActiveProvider || null);
  const [isSwitching, setIsSwitching] = useState<boolean>(false);
  const [notice, setNotice] = useState<{
    text: string;
    type: "success" | "error";
  } | null>(null);

  // Sync with prop updates if provided
  useEffect(() => {
    if (initialProviders && initialProviders.length > 0) {
      setProviders(initialProviders);
    }
  }, [initialProviders]);

  useEffect(() => {
    if (initialActiveProvider) {
      setActiveProvider(initialActiveProvider);
    }
  }, [initialActiveProvider]);

  // Fetch providers and active status on initial mount if not provided via props
  const fetchProviderData = useCallback(async () => {
    try {
      const [listRes, activeRes] = await Promise.all([
        apiFetch("/api/providers"),
        apiFetch("/api/providers/active"),
      ]);

      if (listRes.ok) {
        const listData = await listRes.json();
        if (listData.providers && Array.isArray(listData.providers)) {
          setProviders(listData.providers);
        }
      }

      if (activeRes.ok) {
        const activeData = await activeRes.json();
        if (activeData.provider && activeData.model) {
          setActiveProvider({
            provider: activeData.provider,
            model: activeData.model,
          });
        }
      }
    } catch (err) {
      console.warn("Failed to load providers list from backend API:", err);
    }
  }, []);

  useEffect(() => {
    if (
      !initialProviders ||
      initialProviders.length === 0 ||
      !initialActiveProvider
    ) {
      fetchProviderData();
    }
  }, [initialProviders, initialActiveProvider, fetchProviderData]);

  // Auto-dismiss status notice after 4 seconds
  useEffect(() => {
    if (notice) {
      const timer = setTimeout(() => setNotice(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [notice]);

  /**
   * Dispatches provider/model change to the backend server.
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
      const res = await apiFetch("/api/providers/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, model }),
      });

      if (res.ok) {
        const newState = { provider, model };
        setActiveProvider(newState);
        setNotice({
          text: `Switched to ${provider} (${model})`,
          type: "success",
        });
        if (onSwitch) {
          onSwitch(newState);
        }
      } else {
        const body = await res.json().catch(() => ({}));
        setNotice({
          text: `Failed to switch: ${body?.detail || res.statusText}`,
          type: "error",
        });
      }
    } catch (err: any) {
      setNotice({
        text: `Error switching provider: ${err?.message || "Network error"}`,
        type: "error",
      });
    } finally {
      setIsSwitching(false);
    }
  };

  const selectedValue = activeProvider
    ? `${activeProvider.provider}:${activeProvider.model}`
    : "";

  return (
    <div className="provider-selector flex items-center gap-2 flex-wrap">
      <div className="provider-selector-bar flex items-center gap-2 bg-surface-soft p-1.5 rounded-lg border border-border">
        <span className="provider-label text-xs font-semibold text-muted">
          Provider:
        </span>
        <select
          value={selectedValue}
          disabled={isSwitching}
          onChange={(e) => {
            const val = e.target.value;
            const colonIdx = val.indexOf(":");
            if (colonIdx !== -1) {
              const provider = val.substring(0, colonIdx);
              const model = val.substring(colonIdx + 1);
              handleSwitch(provider, model);
            }
          }}
          className="provider-select text-xs bg-bg text-text border border-border rounded px-2 py-1 focus:outline-none cursor-pointer"
        >
          {providers.length === 0 && (
            <option value="">No providers configured</option>
          )}
          {providers.map((p, idx) => (
            <option
              key={`${p.name}-${p.model}-${idx}`}
              value={`${p.name}:${p.model}`}
            >
              {p.name} ({p.model})
            </option>
          ))}
        </select>

        {isSwitching ? (
          <div className="flex items-center gap-1 text-xs text-brand-purple">
            <Spinner size="sm" />
            <span>Switching...</span>
          </div>
        ) : (
          activeProvider && (
            <Chip size="sm" variant="secondary" className="text-xs">
              {activeProvider.provider} → {activeProvider.model}
            </Chip>
          )
        )}
      </div>

      {notice && (
        <div
          className={`provider-notice text-xs px-2.5 py-1 rounded transition-opacity ${
            notice.type === "success"
              ? "bg-green-100 text-green-800 border border-green-300 dark:bg-green-950 dark:text-green-200"
              : "bg-red-100 text-red-800 border border-red-300 dark:bg-red-950 dark:text-red-200"
          }`}
        >
          {notice.text}
        </div>
      )}
    </div>
  );
}

export default ProviderSelector;
