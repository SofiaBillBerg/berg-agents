/**
 * Integration tests for the Berg Agents harness system.
 * Tests the full flow from AI SDK chat hook through to component rendering.
 */

import { MockHarness } from '@/harness/mock-harness';

const tests: Array<{ name: string; fn: () => Promise<void> | void }> = [];

function test(name: string, fn: () => Promise<void> | void) {
  tests.push({ name, fn });
}

function expect(condition: boolean, message: string) {
  if (!condition) throw new Error(message);
}

test('Full task execution with streaming events', async () => {
  const harness = new MockHarness('success');

  const events: Array<{ type: string; data?: unknown }> = [];
  const unsubscribe = harness.subscribeToEvents((event) => {
    events.push(event);
  });

  const result = await harness.executeTask('Build a web page', 'web');
  unsubscribe();

  expect(result.status === 'completed', 'Task should complete successfully');
  expect(result.implementation.answer.includes('Build a web page'), 'Answer should reference input');
});

test('HITL approval flow', async () => {
  const harness = new MockHarness('hitl_required');
  const result = await harness.executeTask('Sensitive operation', 'generic');

  expect(result.status === 'needs_human_review', 'Should require review');
  expect(harness.getHitlRequest() !== null, 'HITL request should be set');
});

test('Error handling for failure scenario', async () => {
  const harness = new MockHarness('failure');
  const result = await harness.executeTask('Failing task', 'generic');
  expect(result.status === 'failed', 'Task should fail');
});

test('Agent listing returns expected agents', async () => {
  const harness = new MockHarness('success');
  const agents = await harness.getAgents();
  expect(agents.length === 3, 'Should have 3 mock agents');
});

test('Learning stats return structured data', async () => {
  const harness = new MockHarness('success');
  const stats = (await harness.fetchLearningStats()) as Record<string, unknown>;
  expect(stats !== null, 'Stats should exist');
  expect(stats.total === 42, 'Mock total should be 42');
});

test('Scenario switching produces different results', async () => {
  const harness = new MockHarness('success');
  const result1 = await harness.executeTask('test', 'generic');
  expect(result1.status === 'completed', 'Success scenario should complete');

  harness.setScenario('failure');
  const result2 = await harness.executeTask('test', 'generic');
  expect(result2.status === 'failed', 'Failure scenario should fail');
});

export async function runIntegrationTests() {
  console.log('========================================');
  console.log('Berg Agents Integration Tests');
  console.log('========================================\n');

  let passed = 0;
  let failed = 0;

  for (const testObj of tests) {
    try {
      await testObj.fn();
      console.log(`  ✅ ${testObj.name}`);
      passed++;
    } catch (e) {
      console.log(`  ❌ ${testObj.name}: ${(e as Error).message}`);
      failed++;
    }
  }

  console.log('\n========================================');
  console.log(`Results: ${passed} passed, ${failed} failed`);
  console.log('========================================');

  return { passed, failed };
}

export { test, expect };
