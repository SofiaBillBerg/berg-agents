import { useCallback, useEffect, useState } from "react";
import { Alert, Label, ListBox, Select, Spinner } from "@heroui/react";

import { apiFetch } from "@/envConfig";

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

  // Sync with prop updates if provided. Adjusted during render (React
  // discards this pass and re-renders immediately) instead of in effects, to
  // avoid synchronous setState cascades — same pattern as HitlSurface and
  // SlashCommandPicker.
  const [prevInitialProviders, setPrevInitialProviders] =
    useState(initialProviders);
  if (prevInitialProviders !== initialProviders) {
    setPrevInitialProviders(initialProviders);
    if (initialProviders && initialProviders.length > 0) {
      setProviders(initialProviders);
    }
  }

  const [prevInitialActiveProvider, setPrevInitialActiveProvider] = useState(
    initialActiveProvider,
  );
  if (prevInitialActiveProvider !== initialActiveProvider) {
    setPrevInitialActiveProvider(initialActiveProvider);
    if (initialActiveProvider) {
      setActiveProvider(initialActiveProvider);
    }
  }

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
      // Surface fetch failures in the UI notice (auto-dismissed after 4s by
      // the existing timer) instead of logging to the console.
      const detail = err instanceof Error ? err.message : "Network error";
      setNotice({
        text: `Failed to load providers list from backend API: ${detail}`,
        type: "error",
      });
    }
  }, []);

  useEffect(() => {
    if (
      !initialProviders ||
      initialProviders.length === 0 ||
      !initialActiveProvider
    ) {
      // Deferred to a microtask so the fetch's state updates land outside
      // the effect body (react-hooks/set-state-in-effect). Same timing
      // semantics: fires once per prop change when props are absent.
      queueMicrotask(() => {
        void fetchProviderData();
      });
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

  // Key of the active provider in "provider:model" form. Null when nothing is
  // active (or the active pair is not a selectable option) so the Select
  // shows its placeholder instead of a stale value.
  const selectedValue = activeProvider
    ? `${activeProvider.provider}:${activeProvider.model}`
    : null;

  return (
    <div className="provider-selector flex items-center gap-2 flex-wrap">
      <div className="provider-selector-bar flex items-center gap-2 bg-surface-soft p-1.5 rounded-lg border border-border">
        <Select
          aria-label="Provider"
          className="provider-select text-xs"
          isDisabled={isSwitching}
          placeholder={
            providers.length === 0
              ? "No providers configured"
              : "Select provider"
          }
          value={selectedValue}
          onChange={(value) => {
            if (value == null) return;
            const val = String(value);
            const colonIdx = val.indexOf(":");
            if (colonIdx !== -1) {
              const provider = val.substring(0, colonIdx);
              const model = val.substring(colonIdx + 1);
              handleSwitch(provider, model).then((r) => {});
            }
          }}
        >
          <Label>Provider:</Label>
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
      </div>

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
