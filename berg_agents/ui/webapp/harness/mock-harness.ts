/*
 * Mock harness implementation for testing.
 * This provides a predictable test environment without external dependencies.
 */

import type {
  AgentInfo,
  HarnessEvent,
  HitlRequest,
  IHarness,
  TaskComplexity,
  TaskResult,
  HitlDecisionInput
} from './webhook';

// Simple EventEmitter for browser compatibility (no 'events' module needed)
type EventCallback = (event: HarnessEvent) => void;
type EventEmitterLike = {
  on(event: string, callback: EventCallback): void;
  off(event: string, callback: EventCallback): void;
  emit(event: string, ...args: unknown[]): void;
};

function createEventEmitter(): EventEmitterLike {
  const listeners: Map<string, EventCallback[]> = new Map();

  return {
    on(event: string, callback: EventCallback) {
      if (!listeners.has(event)) {
        listeners.set(event, []);
      }
      listeners.get(event)!.push(callback);
    },

    off(event: string, callback: EventCallback) {
      const callbacks = listeners.get(event);
      if (callbacks) {
        const index = callbacks.indexOf(callback);
        if (index > -1) {
          callbacks.splice(index, 1);
        }
      }
    },

    emit(event: string, ...args: unknown[]) {
      const callbacks = listeners.get(event);
      if (callbacks) {
        callbacks.forEach(callback => {
          try {
            if (args[0] !== undefined) {
              callback(args[0] as HarnessEvent);
            }
          } catch (error) {
            console.error(`Error in event handler for ${event}:`, error);
          }
        });
      }
    }
  };
}

// Test data scenarios
const MOCK_AGENTS: AgentInfo[] = [
  {
    name: "researcher",
    model: "gpt-4",
    preferred_complexity: "standard",
    description: "Research and analysis agent",
    capabilities: ["web_search", "document_analysis", "data_extraction"],
  },
  {
    name: "coder",
    model: "claude-3",
    preferred_complexity: "complex",
    description: "Code generation and debugging agent",
    capabilities: ["code_generation", "debugging", "testing"],
  },
  {
    name: "designer",
    model: "gpt-4-vision",
    preferred_complexity: "standard",
    description: "UI/UX and creative design agent",
    capabilities: ["ui_design", "visual_design", "prototyping"],
  }
];

// Task complexity configurations
const TASK_COMPLEXITIES: Record<string, TaskComplexity> = {
  simple: { value: "simple", description: "Simple, straightforward tasks" },
  standard: { value: "standard", description: "Standard tasks requiring moderate analysis" },
  complex: { value: "complex", description: "Complex tasks requiring significant planning" }
};

export class MockHarness implements IHarness {
  private emitter: EventEmitterLike = createEventEmitter();
  private events: HarnessEvent[] = [];
  private currentResult: TaskResult | null = null;
  private hitlRequest: HitlRequest | null = null;
  private isRunning = false;

  // Test scenario configuration
  private scenario: 'success' | 'failure' | 'hitl_required' | 'long_running' = 'success';

  constructor(scenario: 'success' | 'failure' | 'hitl_required' | 'long_running' = 'success') {
    this.scenario = scenario;
  }

  async executeTask(description: string, taskType: string = "generic"): Promise<TaskResult> {
    this.isRunning = true;
    this.events.push({ type: "task_started", data: { description, task_type: taskType } });

    // Simulate network delay
    await new Promise(resolve => setTimeout(resolve, 500));

    let result: TaskResult;

    switch (this.scenario) {
      case 'success':
        result = {
          status: "completed",
          task_id: `task-${Date.now()}`,
          complexity: TASK_COMPLEXITIES.standard,
          implementation: {
            answer: `Successfully completed task: ${description}\n\nResult: Generated analysis report with key insights and recommendations.`
          },
          plan: [
            { step: 1, description: "Analyze task requirements" },
            { step: 2, description: "Research relevant information" },
            { step: 3, description: "Generate structured output" }
          ],
          curation: { status: "approved" },
          subagents: ["researcher"],
          background_tasks: []
        } as TaskResult;
        break;

      case 'failure':
        result = {
          status: "failed",
          task_id: `task-${Date.now()}`,
          complexity: TASK_COMPLEXITIES.simple,
          implementation: {
            answer: "Task execution failed due to insufficient permissions."
          },
          curation: { status: "rejected" }
        } as TaskResult;
        break;

      case 'hitl_required':
        // Simulate a task that requires human review
        result = {
          status: "needs_human_review",
          task_id: `task-${Date.now()}`,
          complexity: TASK_COMPLEXITIES.complex,
          implementation: {
            answer: "Generated response but requires human review due to potential risks."
          },
          curation: { status: "pending_review" }
        } as TaskResult;
        this.hitlRequest = {
          task_id: result.task_id,
          description,
          review_reasons: [
            "Potential security implications",
            "Privacy-sensitive data handling",
            "Compliance verification required"
          ],
          risk_level: "high",
          complexity: TASK_COMPLEXITIES.complex
        };
        break;

      case 'long_running':
        // Simulate a task that takes time to complete
        await new Promise(resolve => setTimeout(resolve, 2000));
        result = {
          status: "completed",
          task_id: `task-${Date.now()}`,
          complexity: TASK_COMPLEXITIES.complex,
          implementation: {
            answer: "Long-running task completed successfully.\n\nFinal report generated with comprehensive analysis."
          },
          plan: [
            { step: 1, description: "Initialize complex analysis" },
            { step: 2, description: "Process large dataset" },
            { step: 3, description: "Generate detailed report" },
            { step: 4, description: "Quality assurance review" }
          ],
          curation: { status: "approved" }
        } as TaskResult;
        break;

      default:
        result = {
          status: "completed",
          task_id: `task-${Date.now()}`,
          complexity: TASK_COMPLEXITIES.standard,
          implementation: {
            answer: `Task completed: ${description}`
          }
        } as TaskResult;
        break;
    }

    this.currentResult = result;
    this.events.push({ type: "task_completed", data: result });
    this.isRunning = false;

    // Simulate event streaming
    setTimeout(() => {
      this.emitter.emit('event', { type: "task_completed", data: result });
    }, 100);

    return result;
  }

  async getAgents(): Promise<AgentInfo[]> {
    await new Promise(resolve => setTimeout(resolve, 300));
    return [...MOCK_AGENTS];
  }

  async fetchLearningStats(): Promise<unknown> {
    await new Promise(resolve => setTimeout(resolve, 200));
    return {
      total: 42,
      completed: 38,
      failed: 4,
      approval_rate: 0.904,
      average_completion_time: 1200,
      learning_insights: [
        "Tasks with researcher agent show 95% success rate",
        "Code generation tasks benefit from context optimization",
        "HITL approvals correlate with task complexity"
      ]
    };
  }

  async respondToHitl(threadId: string, decision: HitlDecisionInput): Promise<TaskResult | null> {
    this.hitlRequest = null;

    await new Promise(resolve => setTimeout(resolve, 300));

    if (decision === "approve") {
      return {
        status: "completed",
        task_id: threadId,
        complexity: TASK_COMPLEXITIES.complex,
        implementation: {
          answer: `Task ${threadId} approved and completed successfully.\n\nGenerated final output based on human approval.`
        },
        curation: { status: "approved" }
      } as TaskResult;
    } else if (decision === "reject") {
      return {
        status: "failed",
        task_id: threadId,
        complexity: TASK_COMPLEXITIES.complex,
        implementation: {
          answer: `Task ${threadId} rejected by user. No changes were made.`
        },
        curation: { status: "rejected" }
      } as TaskResult;
    }

    return null;
  }

  subscribeToEvents(callback: (event: HarnessEvent) => void): () => void {
    this.emitter.on('event', callback);

    return () => {
      this.emitter.off('event', callback);
    };
  }

  getCurrentEvents(): HarnessEvent[] {
    return [...this.events];
  }

  getCurrentResult(): TaskResult | null {
    return this.currentResult;
  }

  getHitlRequest(): HitlRequest | null {
    return this.hitlRequest;
  }

  isConnected(): boolean {
    return true;
  }

  reconnect(): void {
    // Mock reconnection - just reset state
    this.events = [];
    this.currentResult = null;
    this.hitlRequest = null;
    this.isRunning = false;
  }

  // Test control methods
  setScenario(scenario: 'success' | 'failure' | 'hitl_required' | 'long_running') {
    this.scenario = scenario;
  }

  addEvent(type: string, data?: unknown) {
    this.events.push({ type, data });
    this.emitter.emit('event', { type, data });
  }
}