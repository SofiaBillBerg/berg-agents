/*
 * Test component to verify the new harness interface works correctly.
 * This is a minimal test version using the new simplified harness API.
 */

import React from 'react';

import { HarnessProvider } from '@/harness/harness-provider';
import { useTaskExecution, useAgents, useHarnessState } from '@/harness/hooks';

export function TestHarnessSimple() {
  // Use the new simplified harness state hook
  const harnessState = useHarnessState();
  const { executeTask, isExecuting, result, error } = useTaskExecution();
  const { agents, isLoading: agentsLoading, error: agentsError } = useAgents();
  const [input, setInput] = React.useState('');
  
  return (
    <HarnessProvider initialMode="mock" initialScenario="success">
      <div className="p-6 max-w-4xl mx-auto">
        <h1 className="text-2xl font-bold mb-6">Harness Test - Simplified Version</h1>
        
        {/* Connection Status */}
        <div className="bg-gray-100 p-4 rounded-lg mb-6">
          <h2 className="text-lg font-semibold mb-2">Connection Status</h2>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <span className="font-medium">Connected:</span> {harnessState.connection.isConnected ? '✅' : '❌'}
            </div>
            <div>
              <span className="font-medium">Loading:</span> {harnessState.connection.isLoading ? '⏳' : '✅'}
            </div>
            <div>
              <span className="font-medium">Error:</span> {harnessState.connection.error || 'None'}
            </div>
          </div>
        </div>
        
        {/* Task Execution */}
        <div className="bg-blue-50 p-4 rounded-lg mb-6">
          <h2 className="text-lg font-semibold mb-2">Task Execution</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">Task Description:</label>
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Enter task description..."
                className="w-full p-2 border rounded"
                disabled={isExecuting}
              />
            </div>
            
            <button
              onClick={() => executeTask(input)}
              disabled={!input || isExecuting}
              className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:bg-gray-300"
            >
              {isExecuting ? 'Executing...' : 'Execute Task'}
            </button>
            
            {error && (
              <div className="bg-red-100 p-3 rounded text-red-700">
                Error: {error}
              </div>
            )}
            
            {result && (
              <div className="bg-green-100 p-3 rounded">
                <h3 className="font-semibold mb-2">Result:</h3>
                <pre className="text-sm overflow-auto">
                  {JSON.stringify(result, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>
        
        {/* Agents List */}
        <div className="bg-green-50 p-4 rounded-lg mb-6">
          <h2 className="text-lg font-semibold mb-2">Available Agents</h2>
          {agentsLoading ? (
            <div>Loading agents...</div>
          ) : agentsError ? (
            <div className="text-red-700">Error: {agentsError}</div>
          ) : (
            <div className="grid gap-2">
              {(agents || []).map((agent: Record<string, unknown>) => (
                <div key={agent.name as string} className="bg-white p-3 rounded border">
                  <div className="font-medium">{agent.name as string}</div>
                  <div className="text-sm text-gray-600">
                    Model: {agent.model as string} | Complexity: {agent.preferred_complexity as string}
                  </div>
                  <div className="text-sm text-gray-500">
                    {agent.description as string}
                  </div>
                  <div className="text-xs text-gray-400">
                    Capabilities: {(agent.capabilities as string[] | undefined)?.join(', ')}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        
        {/* Events Log */}
        <div className="bg-gray-50 p-4 rounded-lg">
          <h2 className="text-lg font-semibold mb-2">Event Log ({harnessState.events.length} events)</h2>
          <div className="max-h-64 overflow-auto">
            {harnessState.events.map((event, index) => (
              <div key={index} className="text-xs font-mono border-b py-1">
                <span className="text-blue-600">{event.type}</span>
                <pre className="mt-1 overflow-auto">
                  {JSON.stringify(event.data, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        </div>
      </div>
    </HarnessProvider>
  );
}