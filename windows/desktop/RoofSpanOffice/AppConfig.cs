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

        // Backend-readiness polling is bounded by a REAL overall DEADLINE (not attempt-count x delay). The
        // shell probes /api/health repeatedly; each probe has a SHORT individual timeout, the loop stops the
        // instant the backend is healthy, and the whole wait can never materially exceed the overall
        // deadline. When the deadline expires we show the branded Retry/Close failure screen. No infinite
        // retry loop.
        public const int ReadinessOverallTimeoutMs = 60000;   // ~60s hard ceiling on startup wait
        public const int ReadinessDelayMs = 1000;             // pause between probes
        public const int HealthRequestTimeoutMs = 3000;       // per-probe timeout (short)

        public static TimeSpan ReadinessOverallTimeout => TimeSpan.FromMilliseconds(ReadinessOverallTimeoutMs);
        public static TimeSpan HealthRequestTimeout => TimeSpan.FromMilliseconds(HealthRequestTimeoutMs);

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
