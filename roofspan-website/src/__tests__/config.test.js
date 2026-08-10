import { resolveInstaller } from "../config";

describe("Windows installer config (public website)", () => {
  test("default production URL is the CloudFront installer", () => {
    const { url } = resolveInstaller({});
    expect(url).toBe("https://downloads.roofspan.io/latest/RoofSpanSetup.exe");
  });

  test("installer URL never points at a backend / S3 / a proxy", () => {
    const { url } = resolveInstaller({});
    expect(url).toMatch(/^https:\/\/downloads\.roofspan\.io\//);
    expect(url).not.toMatch(/s3|amazonaws|\/api\/|localhost|backend/i);
  });

  test("availability flag parses true/false from env", () => {
    expect(resolveInstaller({ REACT_APP_WINDOWS_INSTALLER_AVAILABLE: "true" }).available).toBe(true);
    expect(resolveInstaller({ REACT_APP_WINDOWS_INSTALLER_AVAILABLE: "false" }).available).toBe(false);
    expect(resolveInstaller({}).available).toBe(false);
  });

  test("respects an env override but stays on the CloudFront host", () => {
    const custom = "https://downloads.roofspan.io/latest/RoofSpanSetup.exe?v=2";
    expect(resolveInstaller({ REACT_APP_WINDOWS_INSTALLER_URL: custom }).url).toBe(custom);
  });

  test("update manifest url defaults to the CloudFront manifest", () => {
    expect(resolveInstaller({}).updateManifestUrl).toBe("https://downloads.roofspan.io/update/windows/latest.json");
  });
});
