import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const modules =
  process.env.LOOP_PLAYWRIGHT_MODULES ||
  path.join(root, "desktop/node_modules");
if (
  !fs.existsSync(path.join(modules, "playwright-core")) &&
  !fs.existsSync(path.join(modules, "playwright"))
)
  throw new Error(
    "기존 Playwright가 필요합니다. 설치는 자동 실행하지 않습니다.",
  );
const output =
  process.env.LOOP_RENDERER_OUTPUT ||
  path.join(root, "desktop/verification/renderer");
const p = spawnSync(
  process.execPath,
  [
    path.join(root, "tests/browser/board_e2e.mjs"),
    "--modules",
    modules,
    "--python",
    process.env.PYTHON || "python3",
    "--output",
    output,
  ],
  {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  },
);
process.exitCode = p.status ?? 1;
