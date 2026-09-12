#!/usr/bin/env node
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const backup = process.env.BACKUP;
const dest = process.env.DEST;
const jarvis = process.env.JARVIS;
if (!backup || !dest || !jarvis) {
  process.stderr.write("BACKUP, DEST, and JARVIS must be set\n");
  process.exit(1);
}
const { restoreSqlite } = await import(pathToFileURL(join(jarvis, "src/personal-os-backup.js")).href);
const result = restoreSqlite({ backupPath: backup, destPath: dest });
process.stdout.write(`${JSON.stringify(result)}\n`);
