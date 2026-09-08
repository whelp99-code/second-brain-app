// Strict native completion audit for the opt-in reference/model acceptance probe.
import assert from 'node:assert/strict';
export const REFERENCE_ANSWER_FIELDS = ['answer', 'record_id', 'record_digest', 'text_digest', 'source_identity_full', 'generation_id'];
export function auditReferenceModelEvents(text) {
  const events = text.split('\n').filter(line => line.trim()).map(line => JSON.parse(line));
  const threads = events.filter(event => event.type === 'thread.started');
  assert.equal(threads.length, 1); assert.equal(typeof threads[0].thread_id, 'string');
  assert(threads[0].thread_id.length > 0);
  const starts = events.filter(event => event.type === 'turn.started');
  const completions = events.filter(event => event.type === 'turn.completed');
  assert.equal(starts.length, 1); assert.equal(completions.length, 1);
  assert(events.indexOf(threads[0]) < events.indexOf(starts[0]));
  assert(events.indexOf(starts[0]) < events.indexOf(completions[0]));
  assert(!events.some(event => ['error', 'turn.failed'].includes(event.type)));
  const items = events.filter(event => event.type.startsWith('item.'));
  assert(items.every(event => ['agent_message', 'reasoning'].includes(event.item?.type)), 'Unexpected tool/error item');
  const messages = items.filter(event => event.type === 'item.completed' && event.item.type === 'agent_message');
  assert.equal(messages.length, 1);
  assert(events.indexOf(starts[0]) < events.indexOf(messages[0]));
  assert(events.indexOf(messages[0]) < events.indexOf(completions[0]));
  const response = JSON.parse(messages[0].item.text);
  assert.deepEqual(Object.keys(response).sort(), ['state', ...REFERENCE_ANSWER_FIELDS].sort());
  assert(['answered', 'no_data'].includes(response.state));
  for (const field of REFERENCE_ANSWER_FIELDS) {
    if (response.state === 'no_data') assert.equal(response[field], null);
    else assert(typeof response[field] === 'string' && response[field].length > 0);
  }
  return {response, thread_id: threads[0].thread_id};
}
