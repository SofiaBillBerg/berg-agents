import React, { useEffect, useState } from "react";
import { apiFetch } from "../../envConfig";

/**
 * ProviderSelector component
 * Displays available providers and allows switching active provider
 * Shows auto-dismiss notification on successful switch
 */
function ProviderSelector({ activeProvider, providers, onSwitch }) {
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    // Auto-dismiss notification after 5 seconds
    if (notice) {
      const timer = setTimeout(() => setNotice(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [notice]);

  const handleSwitch = async (provider: string, model: string) => {
    if (
      provider === activeProvider?.provider &&
      model === activeProvider?.model
    ) {
      return; // No-op if already selected
    }
    try {
      const res = await apiFetch("/providers/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, model }),
      });
      if (res.ok) {
        setNotice(`Switched to ${provider} (${model})`);
        if (onSwitch) onSwitch({ provider, model });
      } else {
        const body = await res.json().catch(() => ({}));
        setNotice(`Failed to switch: ${body?.detail || res.statusText}`);
      }
    } catch (err) {
      setNotice(`Error switching provider: ${err.message}`);
    }
  };

  return (
    <div className="provider-selector">
      <div className="provider-selector-bar">
        <span className="provider-label">Provider:</span>
        <select
          value={
            activeProvider
              ? `${activeProvider.provider}:${activeProvider.model}`
              : ""
          }
          onChange={(e) => {
            const [provider, model] = e.target.value.split(":");
            if (provider && model)
              handleSwitch(provider, model)
                .then((r) => {})
                .catch((e) => {});
          }}
          className="provider-select"
        >
          {providers?.map(
            (
              p: {
                name:
                  | string
                  | number
                  | bigint
                  | boolean
                  | React.ReactElement<
                      unknown,
                      string | React.JSXElementConstructor<any>
                    >
                  | Iterable<React.ReactNode>
                  | React.ReactPortal
                  | Promise<
                      | string
                      | number
                      | bigint
                      | boolean
                      | React.ReactPortal
                      | React.ReactElement<
                          unknown,
                          string | React.JSXElementConstructor<any>
                        >
                      | Iterable<React.ReactNode>
                      | null
                      | undefined
                    >
                  | null
                  | undefined;
                model:
                  | string
                  | number
                  | bigint
                  | boolean
                  | React.ReactElement<
                      unknown,
                      string | React.JSXElementConstructor<any>
                    >
                  | Iterable<React.ReactNode>
                  | React.ReactPortal
                  | Promise<
                      | string
                      | number
                      | bigint
                      | boolean
                      | React.ReactPortal
                      | React.ReactElement<
                          unknown,
                          string | React.JSXElementConstructor<any>
                        >
                      | Iterable<React.ReactNode>
                      | null
                      | undefined
                    >
                  | null
                  | undefined;
              },
              idx: React.Key | null | undefined,
            ) => (
              <option key={idx} value={`${p.name}:${p.model}`}>
                {p.name} ({p.model})
              </option>
            ),
          )}
        </select>
        <span className="provider-active">
          {activeProvider
            ? `${activeProvider.provider} → ${activeProvider.model}`
            : "Loading..."}
        </span>
      </div>
      {notice && (
        <div
          className={`provider-notice ${notice.startsWith("Switched") ? "success" : "error"}`}
        >
          {notice}
          {notice.startsWith("Switched") && (
            <span className="provider-notice-dismiss">Auto-dismissing...</span>
          )}
        </div>
      )}
    </div>
  );
}

export default ProviderSelector;
