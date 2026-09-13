import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
const local = fileURLToPath(new URL(process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python', import.meta.url));
const result = spawnSync(existsSync(local) ? local : (process.platform === 'win32' ? 'python' : 'python3'), process.argv.slice(2), {cwd:root, stdio:'inherit'});
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
