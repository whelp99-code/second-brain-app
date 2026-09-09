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
  const json = fenced ? fenced[1] : text;
  const value = JSON.parse(json);
  // JSON.parse keeps the last duplicate property. Inspect complete string tokens
  // so contradictory earlier fields cannot disappear from acceptance evidence.
  const keys = new Set();
  for (let i = 0; i < json.length; i++) {
    if (json[i] !== '"') continue;
    const start = i++;
    while (i < json.length && json[i] !== '"') {
      if (json[i] === '\\') i++;
      i++;
    }
    let next = i + 1;
    while (/\s/.test(json[next] ?? '') && next < json.length) next++;
    if (json[next] === ':') {
      const key = JSON.parse(json.slice(start, i + 1));
      assert(!keys.has(key), 'Duplicate answer field');
      keys.add(key);
    }
  }
  assert(value !== null && typeof value === 'object' && !Array.isArray(value));
  assert.deepEqual(Object.keys(value).sort(), ['explanation', 'status', 'value']);
  assert.equal(value.status, status);
  assert.equal(value.value, expected);
  assert.equal(typeof value.explanation, 'string');
  assert(value.explanation.trim());
  return { ...value, raw_response: text };
}
