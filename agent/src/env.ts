import { config as loadEnv } from "dotenv";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

loadEnv({
  path: [resolve(repoRoot, ".env.local"), resolve(repoRoot, ".env")],
  quiet: true,
});
