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

import type {ActiveProviderState, ProviderItem} from "../actions/providers";
import {getProviderData, switchProvider} from "../actions/providers";

import {useCallback, useEffect, useState} from "react";
import {Alert, ListBox, Select, Spinner} from "@heroui/react";

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

    // Sync with prop updates if provided (same pattern as other components)
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

    // Fetch providers and active status via actions layer if not provided via props
    const fetchProviderData = useCallback(async () => {
        try {
            const data = await getProviderData();
            setProviders(data.providers);
            if (data.active) {
                setActiveProvider(data.active);
            }
        } catch (err) {
            const detail = err instanceof Error ? err.message : "Network error";
            setNotice({
                text: `Failed to load providers list from backend API: ${detail}`,
                type: "error"});
        }
    }, []);

    useEffect(() => {
        if (
            !initialProviders ||
            initialProviders.length === 0 ||
            !initialActiveProvider
        ) {
            // Deferred to a microtask so the fetch's state updates land outside
            // the effect body to avoid synchronous setState cascades.
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
                const newState = result.active || {provider, model};
                setActiveProvider(newState);
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
                    <Select.Value/>
                    <Select.Indicator/>
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
                                <ListBox.ItemIndicator/>
                            </ListBox.Item>
                        ))}
                    </ListBox>
                </Select.Popover>
            </Select>

            {isSwitching && (
                <div className="flex items-center gap-1 text-xs text-brand-purple">
                    <Spinner size="sm"/>
                    <span>Switching...</span>
                </div>
            )}

            {notice && (
                <Alert status={notice.type === "success" ? "success" : "danger"}>
                    <Alert.Indicator/>
                    <Alert.Content>
                        <Alert.Title>{notice.text}</Alert.Title>
                    </Alert.Content>
                </Alert>
            )}
        </div>
    );
}

export default ProviderSelector;
