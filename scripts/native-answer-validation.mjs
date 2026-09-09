import assert from 'node:assert/strict';

// Accept one complete response, never silently discard prose outside its JSON.
export function parseInsufficientEvidenceAnswer(raw) {
  return parseAnswer(raw, 'insufficient_evidence', null);
}

export function parseSupportedEvidenceAnswer(raw, expected) {
  assert.equal(typeof expected, 'string');
  assert(expected.trim());
  return parseAnswer(raw, 'supported', expected);
}

function parseAnswer(raw, status, expected) {
  assert.equal(typeof raw, 'string');
  const text = raw.trim();
  const fenced = /^```(?:json)?\s*([\s\S]*?)```\s*$/.exec(text);
  const value = JSON.parse(fenced ? fenced[1] : text);
  assert(value !== null && typeof value === 'object' && !Array.isArray(value));
  assert.deepEqual(Object.keys(value).sort(), ['explanation', 'status', 'value']);
  assert.equal(value.status, status);
  assert.equal(value.value, expected);
  assert.equal(typeof value.explanation, 'string');
  assert(value.explanation.trim());
  return { ...value, raw_response: text };
}
