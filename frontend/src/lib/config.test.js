import { resolveInstaller, WINDOWS_INSTALLER_URL } from "./config";

describe("Windows installer config", () => {
  test("default production URL is the CloudFront installer", () => {
    const { url } = resolveInstaller({});
    expect(url).toBe("https://downloads.roofspan.io/latest/RoofSpanSetup.exe");
    expect(new URL(url).hostname).toBe("downloads.roofspan.io");
  });

  test("installer URL never points at the backend / S3 / a proxy", () => {
    const u = WINDOWS_INSTALLER_URL;
    expect(u).toMatch(/^https:\/\/downloads\.roofspan\.io\//);
    expect(u).not.toMatch(/amazonaws\.com|s3\.|localhost|\/api\/|preview\.emergentagent|vercel|railway/i);
  });

  test("availability flag parses true/false from env", () => {
    expect(resolveInstaller({ REACT_APP_WINDOWS_INSTALLER_AVAILABLE: "true" }).available).toBe(true);
    expect(resolveInstaller({ REACT_APP_WINDOWS_INSTALLER_AVAILABLE: "false" }).available).toBe(false);
    expect(resolveInstaller({}).available).toBe(false); // safe default: coming soon
  });

  test("respects an env override but keeps the CloudFront host", () => {
    const { url } = resolveInstaller({
      REACT_APP_WINDOWS_INSTALLER_URL: "https://downloads.roofspan.io/releases/RoofSpanSetup-1.0.0.exe",
    });
    expect(url).toBe("https://downloads.roofspan.io/releases/RoofSpanSetup-1.0.0.exe");
  });

  test("update manifest url defaults to the CloudFront manifest", () => {
    expect(resolveInstaller({}).updateManifestUrl).toBe("https://downloads.roofspan.io/update/windows/latest.json");
  });
});
