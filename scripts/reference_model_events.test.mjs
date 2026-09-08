import assert from 'node:assert/strict';
import {test} from 'node:test';
import {auditReferenceModelEvents, REFERENCE_ANSWER_FIELDS} from './reference_model_events.mjs';
const body = {state: 'no_data', ...Object.fromEntries(REFERENCE_ANSWER_FIELDS.map(key => [key, null]))};
const baseline = () => [
  {type: 'thread.started', thread_id: 'fixture-thread'}, {type: 'turn.started'},
  {type: 'item.completed', item: {type: 'agent_message', text: JSON.stringify(body)}}, {type: 'turn.completed'},
];
const encode = events => events.map(event => JSON.stringify(event)).join('\n');
test('requires native completion and preserves its thread identity', () => {
  assert.deepEqual(auditReferenceModelEvents(encode(baseline())), {response: body, thread_id: 'fixture-thread'});
});
for (const [name, modify] of [
  ['missing thread', events => events.slice(1)],
  ['missing completion', events => events.slice(0, -1)],
  ['duplicate completion', events => [...events, {type: 'turn.completed'}]],
  ['failure after a completion', events => [...events, {type: 'turn.failed'}]],
  ['top-level error', events => [...events, {type: 'error', message: 'failure'}]],
  ['started unfinished tool', events => [...events.slice(0, 2), {type: 'item.started', item: {type: 'command_execution'}}, ...events.slice(2)]],
  ['completed tool', events => [...events.slice(0, 2), {type: 'item.completed', item: {type: 'mcp_tool_call'}}, ...events.slice(2)]],
  ['item error', events => [...events.slice(0, 2), {type: 'item.completed', item: {type: 'error'}}, ...events.slice(2)]],
  ['multiple answers', events => [...events.slice(0, 3), events[2], events[3]]],
  ['answer after completion', events => [events[0], events[1], events[3], events[2]]],
  ['completion before turn', events => [events[0], events[3], events[1], events[2]]],
  ['unstructured answer', events => events.map(event => event.item ? {...event, item: {...event.item, text: 'done'}} : event)],
  ['no-data with invented answer', events => events.map(event => event.item ? {...event, item: {...event.item,
    text: JSON.stringify({...body, answer: 'invented'})}} : event)],
]) test(`rejects ${name} even if its process exited zero`, () => {
  assert.throws(() => auditReferenceModelEvents(encode(modify(baseline()))));
});
