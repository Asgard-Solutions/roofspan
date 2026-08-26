import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  timeout: 30000,
  use: { baseURL: "http://127.0.0.1:3100", trace: "off" },
  webServer: {
    command: "npx serve@14 out -l 3100",
    url: "http://127.0.0.1:3100",
    timeout: 60000,
    reuseExistingServer: true,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
