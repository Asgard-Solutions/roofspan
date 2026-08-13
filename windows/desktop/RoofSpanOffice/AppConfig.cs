using System;
using System.IO;

namespace RoofSpanOffice
{
    // Central configuration for the RoofSpan Office desktop shell. No secrets; only local URLs + paths.
    internal static class AppConfig
    {
        public const string WindowTitle = "RoofSpan Office";

        // The local Office UI served by the RoofSpanBackend Windows service. 127.0.0.1 (loopback) ONLY -
        // the backend is never exposed to the LAN. Overridable via ROOFSPAN_OFFICE_URL for dev/test/custom
        // deployments (same override the previous launcher supported); the internal-navigation allow-list is
        // derived from whatever base URL resolves, so the override stays self-consistent.
        public const string DefaultBaseUrl = "http://127.0.0.1:8001/";
        public const string HealthPath = "api/health";

        // Backend-readiness polling is BOUNDED (no infinite hang). ~60s total tolerates a cold boot where the
        // Windows services are still starting; if it never becomes healthy we show a branded failure screen.
        public const int ReadinessMaxAttempts = 40;
        public const int ReadinessDelayMs = 1500;
        public const int HealthRequestTimeoutMs = 3000;

        public static string BaseUrl()
        {
            var v = Environment.GetEnvironmentVariable("ROOFSPAN_OFFICE_URL");
            if (string.IsNullOrWhiteSpace(v)) return DefaultBaseUrl;
            v = v.Trim();
            if (!v.EndsWith("/")) v += "/";
            return v;
        }

        public static Uri BaseUri() => new Uri(BaseUrl());

        public static string HealthUrl() => new Uri(BaseUri(), HealthPath).ToString();

        private static string LocalAppRoot()
        {
            var baseDir = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            var dir = Path.Combine(baseDir, "RoofSpan", "Office");
            Directory.CreateDirectory(dir);
            return dir;
        }

        // Per-user, writable WebView2 profile (cache/cookies/session). NEVER under Program Files and NEVER
        // mixed with PostgreSQL data or backend secrets.
        public static string WebView2UserDataFolder()
        {
            var dir = Path.Combine(LocalAppRoot(), "WebView2");
            Directory.CreateDirectory(dir);
            return dir;
        }

        public static string WindowStateFile() => Path.Combine(LocalAppRoot(), "window.json");
    }
}
