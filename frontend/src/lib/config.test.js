import { resolveInstaller, versionedInstallerUrl } from "./config";

describe("Office UI Windows installer config", () => {
  test("defaults to the CloudFront installer, never a backend/S3/proxy", () => {
    const { url } = resolveInstaller({});
    expect(url).toBe("https://downloads.roofspan.io/latest/RoofSpanSetup.exe");
    expect(url).not.toMatch(/s3|amazonaws|\/api\/|localhost|backend/i);
  });

  test("availability flag parses from env", () => {
    expect(resolveInstaller({ REACT_APP_WINDOWS_INSTALLER_AVAILABLE: "true" }).available).toBe(true);
    expect(resolveInstaller({}).available).toBe(false);
  });

  test("versioned installer URL uses the CloudFront releases path", () => {
    expect(versionedInstallerUrl("1.4.2", {})).toBe("https://downloads.roofspan.io/releases/RoofSpanSetup-1.4.2.exe");
  });
});
