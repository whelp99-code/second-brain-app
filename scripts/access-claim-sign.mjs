// Test fixture signer only: no JARVIS identity/authorization issuance is claimed.
import { readFileSync } from 'node:fs';
import { createPrivateKey, sign } from 'node:crypto';
const value = JSON.parse(readFileSync(0, 'utf8'));
const seed = Buffer.from(Array.from({ length: 32 }, (_, i) => i));
const key = createPrivateKey({ key: Buffer.concat([
  Buffer.from('302e020100300506032b657004220420', 'hex'), seed,
]), format: 'der', type: 'pkcs8' });
function canonical(v) {
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
  return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}';
}
const signature = sign(null, Buffer.from('orca-jarvis/memory-access-claim/v1\0' + canonical(value)), key).toString('base64url');
process.stdout.write(JSON.stringify({ ...value, signature }));
