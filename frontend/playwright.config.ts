import { defineConfig, devices } from "@playwright/test";

const localChrome = process.env.E2E_CHROME_PATH;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "line",
  use: {
    baseURL: "http://127.0.0.1:3210",
    trace: "retain-on-failure",
    ...(localChrome ? { launchOptions: { executablePath: localChrome } } : {}),
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "android", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command: "python ../backend/eval/e2e_server.py",
      url: "http://127.0.0.1:8765/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3210",
      url: "http://127.0.0.1:3210",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { ...process.env, WEAVE_API_BASE: "http://127.0.0.1:8765" },
    },
  ],
});
