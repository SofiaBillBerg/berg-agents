import { Card, Chip, Spinner } from "@heroui/react";

export interface SubtaskItem {
  id?: string;
  description?: string;
  complexity?: "trivial" | "standard" | "complex" | "critical" | string;
  estimated_complexity?: string;
  dependencies?: string[];
}

export interface SubtaskPanelProps {
  subtasks?: SubtaskItem[];
  isPlanning?: boolean;
}

// Semantic HeroUI chip colors per complexity tier (never raw hex).
const COMPLEXITY_COLORS: Record<
  string,
  "default" | "accent" | "success" | "warning" | "danger"
> = {
  trivial: "success",
  standard: "default",
  complex: "warning",
  critical: "danger",
};

/**
 * SubtaskPanel component.
 * Displays planner execution subtasks, complexity tiers, and dependency ordering.
 *
 * @param props - Component properties
 * @returns JSX element rendering the subtasks panel
 */
export function SubtaskPanel({
  subtasks = [],
  isPlanning = false,
}: SubtaskPanelProps) {
  if (!subtasks || subtasks.length === 0) {
    if (isPlanning) {
      return (
        <div
          className="subtask-panel planning flex items-center gap-2 p-3 text-xs"
          role="status"
        >
          <Spinner color="accent" size="sm" />
          <span>Planning task decomposition…</span>
        </div>
      );
    }
    return null;
  }

  return (
    <section aria-label="Execution plan" className="subtask-panel">
      <Card>
        <Card.Header>
          <Card.Title>Execution Plan</Card.Title>
          <Card.Description>{subtasks.length} steps</Card.Description>
        </Card.Header>
        <Card.Content>
          <ol className="m-0 flex list-none flex-col gap-2 p-0">
            {subtasks.map((task, idx) => {
              const compKey = task.complexity
                ? String(task.complexity).toLowerCase()
                : "";
              const color = COMPLEXITY_COLORS[compKey] || "default";
              return (
                <li key={task.id || `subtask-${idx}`}>
                  <Card variant="transparent">
                    <Card.Content className="flex items-start gap-2.5 text-xs">
                      <span
                        aria-hidden="true"
                        className="w-5 shrink-0 text-center font-mono font-bold text-muted"
                      >
                        {idx + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="m-0 font-medium text-foreground">
                          {task.description}
                        </p>
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          {task.complexity && (
                            <Chip color={color} size="sm" variant="primary">
                              {task.complexity}
                            </Chip>
                          )}
                          {task.estimated_complexity && (
                            <Chip size="sm" variant="soft">
                              {task.estimated_complexity}
                            </Chip>
                          )}
                          {task.dependencies &&
                            task.dependencies.length > 0 && (
                              <span className="text-muted">
                                ↳ depends on {task.dependencies.join(", ")}
                              </span>
                            )}
                        </div>
                      </div>
                    </Card.Content>
                  </Card>
                </li>
              );
            })}
          </ol>
        </Card.Content>
      </Card>
    </section>
  );
}

export default SubtaskPanel;
