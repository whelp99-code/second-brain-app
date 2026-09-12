#!/usr/bin/env node
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const jarvis = process.env.JARVIS;
const authorityPath = process.env.AUTHORITY;
const authorityRoot = process.env.AUTHORITY_ROOT;
const fencePath = process.env.FENCE;
if (!jarvis || !authorityPath || !authorityRoot || !fencePath) {
  process.stderr.write("JARVIS, AUTHORITY, AUTHORITY_ROOT, and FENCE must be set\n");
  process.exit(1);
}
const load = name => import(pathToFileURL(join(jarvis, name)).href);
const { AuthorityDb } = await load("src/db.js");
const { createProductionMemoryReadFence } = await load("src/memory-read-fence-production.js");
const authority = new AuthorityDb(authorityPath, undefined, { fileMustExist: true });
try {
  const config = {
    provider_instance_id: "provider:fixture",
    signing_key_id: "jarvis:fixture",
    private_key_path: join(authorityRoot, "memory-read-fixture.pem"),
  };
  const fence = createProductionMemoryReadFence(authority, config, "memory_status")(new Date());
  writeFileSync(fencePath, JSON.stringify(fence));
  process.stdout.write(`${JSON.stringify(fence)}\n`);
} finally {
  authority.close();
}
