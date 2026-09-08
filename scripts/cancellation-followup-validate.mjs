import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const input = JSON.parse(readFileSync(0, 'utf8'));
const { requireMemoryEffectWriteRequest } = await import(pathToFileURL(`${input.build}/src/second-brain-effect-v2.js`));
const request = requireMemoryEffectWriteRequest(input.request, { now: new Date(input.now),
  expectedProvider: 'provider:fixture', delegationKeys: new Map([['jarvis:fixture', input.public_key]]) });
process.stdout.write(JSON.stringify({ pid: process.pid, request_id: request.request_id,
  tombstone_sequence: request.tombstone_high_water.sequence, delta_length: request.tombstone_chain_delta.length }));
