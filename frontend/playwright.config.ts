import { defineConfig, devices } from "@playwright/test";

// Browser smoke test of the built app with no backend: every public page must
// render without an uncaught error. Run `npm run build` first, then
// `npm run test:e2e`. Files are *.e2e.ts so vitest does not pick them up.
const port = 3200;

export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.e2e.ts",
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: { baseURL: `http://127.0.0.1:${port}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npx next start -p ${port} -H 127.0.0.1`,
    url: `http://127.0.0.1:${port}/login`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    // Placeholder auth settings so the server starts; no database or research API.
    env: {
      AUTH_SECRET: "e2e-only-secret-not-used-anywhere-else",
      AUTH_URL: `http://127.0.0.1:${port}`,
      AUTH_TRUST_HOST: "true",
    },
  },
});
