/*
 * Real harness implementation that connects to the Python backend.
 * This provides the actual implementation of the IHarness interface.
 */

import type {
  AgentInfo,
  HarnessEvent,
  HitlRequest,
  IHarness,
  TaskResult,
  HitlDecisionInput
} from './webhook';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8001';

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

export class RealHarness implements IHarness {
  private emitter: EventEmitterLike = createEventEmitter();
  private events: HarnessEvent[] = [];
  private currentResult: TaskResult | null = null;
  private hitlRequest: HitlRequest | null = null;
  private isRunning = false;
  private eventSource: EventSource | null = null;
  private authToken: string | null = null;

  constructor(authToken?: string) {
    this.authToken = authToken || null;
    if (typeof window !== 'undefined') {
      this.setupEventSource();
    }
  }

  private setupEventSource() {
    // Use Server-Sent Events for real-time updates
    this.eventSource = new EventSource(`${BACKEND_URL}/api/harness/events`, {
      withCredentials: true,
    });

    this.eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const harnessEvent: HarnessEvent = {
          type: data.type,
          data: data.data
        };

        this.events.push(harnessEvent);
        this.emitter.emit('event', harnessEvent);

        // Update state based on event type
        if (data.type === 'data-task-completed' && data.data) {
          this.currentResult = data.data as unknown as TaskResult;
        } else if (data.type === 'data-hitl-requested' && data.data) {
          this.hitlRequest = {
            ...data.data,
            description: data.data.description || 'Task requires human review'
          } as unknown as HitlRequest;
        }
      } catch (error) {
        console.error('Error parsing SSE event:', error);
      }
    };

    this.eventSource.onerror = () => {
      console.warn('SSE connection error - attempting reconnect');
      // Attempt reconnection after delay
      setTimeout(() => this.setupEventSource(), 5000);
    };
  }

  async executeTask(description: string, taskType: string = "generic"): Promise<TaskResult> {
    this.isRunning = true;
    this.events.push({ type: "task_started", data: { description, task_type: taskType } });

    try {
      const response = await fetch(`${BACKEND_URL}/api/harness`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(this.authToken && { 'Authorization': `Bearer ${this.authToken}` })
        },
        body: JSON.stringify({ description, task_type: taskType })
      });

      if (!response.ok) {
        throw new Error(`Task execution failed: ${response.statusText}`);
      }

      const result = await response.json() as TaskResult;
      this.currentResult = result;
      this.events.push({ type: "task_completed", data: result });

      return result;

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      this.events.push({ type: "task_failed", data: { error: errorMessage } });
      throw error;
    } finally {
      this.isRunning = false;
    }
  }

  async getAgents(): Promise<AgentInfo[]> {
    try {
      const response = await fetch(`${BACKEND_URL}/api/agents`, {
        headers: {
          'Content-Type': 'application/json',
          ...(this.authToken && { 'Authorization': `Bearer ${this.authToken}` })
        }
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch agents: ${response.statusText}`);
      }

      const agents = await response.json() as AgentInfo[];
      return agents;

    } catch (error) {
      console.error('Error fetching agents:', error);
      // Return fallback agents on error
      return this.getFallbackAgents();
    }
  }

  async fetchLearningStats(): Promise<unknown> {
    try {
      const response = await fetch(`${BACKEND_URL}/api/learning-stats`, {
        headers: {
          'Content-Type': 'application/json',
          ...(this.authToken && { 'Authorization': `Bearer ${this.authToken}` })
        }
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch learning stats: ${response.statusText}`);
      }

      return await response.json();

    } catch (error) {
      console.error('Error fetching learning stats:', error);
      return null;
    }
  }

  async respondToHitl(threadId: string, decision: HitlDecisionInput): Promise<TaskResult | null> {
    try {
      const payload = this.formatHitlDecision(decision);

      const response = await fetch(`${BACKEND_URL}/api/harness/${threadId}/respond`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(this.authToken && { 'Authorization': `Bearer ${this.authToken}` })
        },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        throw new Error(`HITL response failed: ${response.statusText}`);
      }

      const result = await response.json() as TaskResult;
      this.hitlRequest = null;

      if (result) {
        this.currentResult = result;
        this.events.push({ type: "task_resumed", data: result });
      }

      return result;

    } catch (error) {
      console.error('Error responding to HITL:', error);
      throw error;
    }
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
    return this.eventSource?.readyState === EventSource.OPEN;
  }

  reconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
    }
    if (typeof window !== 'undefined') {
      this.setupEventSource();
    }
  }

  // Helper methods
  private formatHitlDecision(decision: HitlDecisionInput): Record<string, unknown> {
    if (typeof decision === 'string') {
      return { decision };
    } else if (Array.isArray(decision)) {
      return {
        decision: decision[0]?.decision || 'approve',
        edited_action: decision[0]?.edited_action || null
      };
    } else {
      return {
        decision: decision.decision || 'approve',
        edited_action: decision.edited_action || null
      };
    }
  }

  private getFallbackAgents(): AgentInfo[] {
    return [
      {
        name: "default",
        model: "fallback-model",
        preferred_complexity: "simple",
        description: "Fallback agent",
        capabilities: ["basic"],
      }
    ];
  }

  // Cleanup
  destroy() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}