import React from "react";

export interface OutcomeRecord {
  success?: number;
  failure?: number;
}

export interface LearningStats {
  total?: number;
  by_task_type?: Record<string, OutcomeRecord>;
  by_model?: Record<string, OutcomeRecord>;
}

export interface LearningPanelProps {
  stats?: LearningStats | null;
  compact?: boolean;
}

/**
 * LearningPanel component.
 * Displays outcome statistics, success rates, and model performance metrics
 * gathered by the learning engine.
 *
 * @param props - Component properties
 * @returns JSX element rendering the learning stats panel
 */
export function LearningPanel({ stats, compact = false }: LearningPanelProps) {
  if (!stats || !stats.total || stats.total === 0) {
    return (
      <div className="learning-panel empty p-3 text-xs text-muted">
        <h4 className="font-semibold text-sm mb-1 text-text">Learning Stats</h4>
        <p>
          No outcomes recorded yet. The learning engine adapts dynamically
          during tasks.
        </p>
      </div>
    );
  }

  const byTaskType = stats.by_task_type || {};
  const byModel = stats.by_model || {};

  if (compact) {
    return (
      <div className="learning-panel compact flex items-center gap-2 text-xs flex-wrap">
        <span className="learning-stat font-medium">{stats.total} tasks</span>
        {Object.entries(byModel).map(([model, data]) => {
          const success = data?.success || 0;
          const failure = data?.failure || 0;
          const total = success + failure;
          const rate = total > 0 ? Math.round((success / total) * 100) : 0;
          return (
            <span key={model} className="learning-stat text-muted">
              {model}: {rate}%
            </span>
          );
        })}
      </div>
    );
  }

  return (
    <div className="learning-panel p-3 bg-surface rounded-lg border border-border">
      <h4 className="font-semibold text-sm text-text">Learning Stats</h4>
      <p className="learning-summary text-xs text-muted mb-3">
        Total tasks evaluated: {stats.total}
      </p>

      {Object.keys(byTaskType).length > 0 && (
        <div className="learning-section mb-3">
          <h5 className="text-xs font-semibold uppercase tracking-wider text-muted mb-1.5">
            By Task Type
          </h5>
          {Object.entries(byTaskType).map(([type, data]) => {
            const success = data?.success || 0;
            const failure = data?.failure || 0;
            const total = success + failure;
            const rate = total > 0 ? Math.round((success / total) * 100) : 0;
            return (
              <div
                key={type}
                className="learning-row flex items-center gap-2 my-1 text-xs"
              >
                <span className="learning-label w-24 truncate">{type}</span>
                <div className="learning-bar flex-1 h-2 bg-surface-tint rounded overflow-hidden">
                  <div
                    className="learning-bar-fill h-full bg-brand-teal"
                    style={{ width: `${rate}%` }}
                  />
                </div>
                <span className="learning-value text-muted w-16 text-right">
                  {rate}% ({total})
                </span>
              </div>
            );
          })}
        </div>
      )}

      {Object.keys(byModel).length > 0 && (
        <div className="learning-section">
          <h5 className="text-xs font-semibold uppercase tracking-wider text-muted mb-1.5">
            By Model
          </h5>
          {Object.entries(byModel).map(([model, data]) => {
            const success = data?.success || 0;
            const failure = data?.failure || 0;
            const total = success + failure;
            const rate = total > 0 ? Math.round((success / total) * 100) : 0;
            return (
              <div
                key={model}
                className="learning-row flex items-center gap-2 my-1 text-xs"
              >
                <span className="learning-label w-24 truncate">{model}</span>
                <div className="learning-bar flex-1 h-2 bg-surface-tint rounded overflow-hidden">
                  <div
                    className="learning-bar-fill h-full bg-brand-blue"
                    style={{ width: `${rate}%` }}
                  />
                </div>
                <span className="learning-value text-muted w-16 text-right">
                  {rate}% ({total})
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default LearningPanel;
