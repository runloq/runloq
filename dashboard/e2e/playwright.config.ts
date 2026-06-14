import { defineConfig } from '@playwright/test';
import path from 'node:path';
import os from 'node:os';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

// Spin up the API on a non-conflicting port (3022) against an ephemeral
// DB in /tmp so the test doesn't touch the live launchd-managed agent
// on :3002.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const E2E_PORT = '3022';
const E2E_DB_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'tracker-e2e-'));
const REPO_ROOT = path.resolve(__dirname, '../../..');

export default defineConfig({
  testDir: '.',
  testMatch: /.*\.spec\.ts$/,
  timeout: 30_000,
  expect: { timeout: 5000 },
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${E2E_PORT}`,
    headless: true,
    actionTimeout: 5000,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `python3.12 -m uvicorn prism.dashboard.api.main:app --host 127.0.0.1 --port ${E2E_PORT} --log-level warning`,
    url: `http://127.0.0.1:${E2E_PORT}/api/healthz`,
    timeout: 30_000,
    reuseExistingServer: false,
    cwd: REPO_ROOT,
    env: {
      PYTHONPATH: REPO_ROOT,
      TRACKER_STATE_DIR: E2E_DB_DIR,
      TRACKER_DB: path.join(E2E_DB_DIR, 'runloq.db'),
    },
  },
});
