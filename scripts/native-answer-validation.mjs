import assert from 'node:assert/strict';

// Accept one complete response, never silently discard prose outside its JSON.
export function parseInsufficientEvidenceAnswer(raw) {
  assert.equal(typeof raw, 'string');
  const text = raw.trim();
  const fenced = /^```(?:json)?\s*([\s\S]*?)```\s*$/.exec(text);
  const value = JSON.parse(fenced ? fenced[1] : text);
  assert(value !== null && typeof value === 'object' && !Array.isArray(value));
  assert.deepEqual(Object.keys(value).sort(), ['explanation', 'status', 'value']);
  assert.equal(value.status, 'insufficient_evidence');
  assert.equal(value.value, null);
  assert.equal(typeof value.explanation, 'string');
  assert(value.explanation.trim());
  return { ...value, raw_response: text };
}
