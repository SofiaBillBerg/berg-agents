/*
 * Test component to verify the new harness interface works correctly.
 * Uses HeroUI v3 components with compound patterns.
 */

import React, { useCallback, useState } from 'react';

import { Button, Card, Chip, Spinner, TextArea } from '@heroui/react';

import { HarnessProvider } from '@/harness/harness-provider';
import { useTaskExecution, useAgents, useLearningStats, useHarnessState, useAISDKChat } from '@/harness';

const SCENARIOS = [
  { key: 'success', label: 'Success' },
  { key: 'failure', label: 'Failure' },
  { key: 'hitl_required', label: 'HITL Required' },
  { key: 'long_running', label: 'Long Running' },
];

function TestHarnessContent() {
  const harnessState = useHarnessState();
  const { executeTask, isExecuting, result, error } = useTaskExecution();
  const { agents } = useAgents();
  const { stats } = useLearningStats();
  const { messages, sendMessage } = useAISDKChat();
  const [input, setInput] = useState('Test task: Build a simple web page');
  const [scenario, setScenario] = useState('success');

  const runTest = useCallback(async () => {
    try {
      await executeTask(input, 'generic');
    } catch (err) {
      console.error('Test failed:', err);
    }
  }, [input, executeTask]);

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      {/* Header Card */}
      <Card variant="default">
        <Card.Header>
          <Card.Title>Harness Test Interface</Card.Title>
        </Card.Header>
        <Card.Content>
          <p className="text-sm text-muted-foreground">
            Test all harness scenarios and verify integration.
          </p>
        </Card.Content>
      </Card>

      {/* Connection Status */}
      <Card variant="default">
        <Card.Header>
          <Card.Title>Connection Status</Card.Title>
        </Card.Header>
        <Card.Content className="flex items-center gap-3">
          <Spinner color="accent" size="sm" />
          <span>{harnessState.connection.isConnected ? 'Connected' : 'Disconnected'}</span>
          {harnessState.connection.error && (
            <Chip color="danger" size="sm" variant="soft">
              {harnessState.connection.error}
            </Chip>
          )}
        </Card.Content>
      </Card>

      {/* Scenario Selector + Test Input */}
      <Card variant="default">
        <Card.Header>
          <Card.Title>Test Configuration</Card.Title>
        </Card.Header>
        <Card.Content className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {SCENARIOS.map((s) => (
              <Chip
                key={s.key}
                color={scenario === s.key ? 'accent' : 'default'}
                onClick={() => setScenario(s.key)}
                variant={scenario === s.key ? 'soft' : 'secondary'}
              >
                {s.label}
              </Chip>
            ))}
          </div>

          <TextArea
            className="w-full"
            placeholder="Enter task description..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />

          <Button
            className="mt-2 bg-accent text-white hover:bg-accent/90"
            isDisabled={isExecuting || !input.trim()}
            onPress={runTest}
            variant="secondary"
          >
            {isExecuting ? 'Running...' : 'Run Test'}
          </Button>
        </Card.Content>
      </Card>

      {/* Results */}
      {result && (
        <Card variant="default">
          <Card.Header>
            <Card.Title>Result</Card.Title>
            <Chip
              color={result.status === 'completed' ? 'success' : result.status === 'failed' ? 'danger' : 'warning'}
              size="sm"
              variant="soft"
            >
              {result.status}
            </Chip>
          </Card.Header>
          <Card.Content>
            <pre className="text-xs whitespace-pre-wrap bg-surface-tint p-3 rounded">
              {JSON.stringify(result, null, 2)}
            </pre>
          </Card.Content>
        </Card>
      )}

      {/* Error */}
      {error && (
        <Card variant="default" className="border-danger">
          <Card.Header>
            <Card.Title className="text-danger">Error</Card.Title>
          </Card.Header>
          <Card.Content>
            <pre className="text-xs text-danger">{error}</pre>
          </Card.Content>
        </Card>
      )}

      {/* AI SDK Messages */}
      {messages.length > 0 && (
        <Card variant="default">
          <Card.Header>
            <Card.Title>AI SDK Messages ({messages.length})</Card.Title>
          </Card.Header>
          <Card.Content>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {messages.map((msg) => (
                <div key={msg.id} className="p-2 rounded bg-surface-tint">
                  <strong className="capitalize">{msg.role}:</strong> {msg.content}
                </div>
              ))}
            </div>
          </Card.Content>
        </Card>
      )}

      {/* Agent List */}
      <Card variant="default">
        <Card.Header>
          <Card.Title>Available Agents ({harnessState.agents.data.length})</Card.Title>
        </Card.Header>
        <Card.Content>
          <div className="grid grid-cols-2 gap-2 text-sm">
            {(harnessState.agents.data || []).map((agent: Record<string, unknown>) => (
              <div key={agent.name as string} className="flex justify-between">
                <span>{agent.name as string}</span>
                <Chip size="sm" variant="soft">
                  {agent.preferred_complexity as string}
                </Chip>
              </div>
            ))}
          </div>
        </Card.Content>
      </Card>

      {/* Learning Stats */}
      {harnessState.learning.stats && (
        <Card variant="default">
          <Card.Header>
            <Card.Title>Learning Stats</Card.Title>
          </Card.Header>
          <Card.Content>
            <pre className="text-xs whitespace-pre-wrap">
              {JSON.stringify(harnessState.learning.stats, null, 2)}
            </pre>
          </Card.Content>
        </Card>
      )}
    </div>
  );
}

/**
 * Test harness component — wraps content in HarnessProvider.
 * Demonstrates proper usage of the new harness interface.
 */
export default function TestHarnessSimple() {
  return (
    <HarnessProvider initialMode="mock" initialScenario="success">
      <TestHarnessContent />
    </HarnessProvider>
  );
}