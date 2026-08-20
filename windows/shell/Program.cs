using System.Diagnostics;
using System.Net.Http;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace RoofSpan.OfficeShell;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new RoofSpanMainForm());
    }
}

internal sealed class RoofSpanMainForm : Form
{
    private static readonly Uri LocalAppUri = new("http://127.0.0.1:8001/");
    private readonly WebView2 _webView = new() { Dock = DockStyle.Fill };
    private readonly Label _status = new()
    {
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleCenter,
        Font = new Font("Segoe UI", 12F, FontStyle.Regular),
        Text = "Starting RoofSpan Office..."
    };

    public RoofSpanMainForm()
    {
        Text = "RoofSpan Office";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(1000, 700);
        Width = 1440;
        Height = 900;

        var iconPath = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "runtime", "RoofSpan.ico"));
        if (File.Exists(iconPath))
        {
            try { Icon = new Icon(iconPath); } catch { }
        }

        Controls.Add(_status);
        Shown += async (_, _) => await InitializeAsync();
    }

    private async Task InitializeAsync()
    {
        if (!await WaitForBackendAsync(TimeSpan.FromSeconds(60)))
        {
            _status.Text = "RoofSpan Office could not connect to the local service.\r\n\r\n" +
                           "Please restart RoofSpan Office. If the problem continues, contact support.";
            return;
        }

        try
        {
            var userDataFolder = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "RoofSpan",
                "WebView2");
            Directory.CreateDirectory(userDataFolder);

            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: userDataFolder);
            Controls.Clear();
            Controls.Add(_webView);
            await _webView.EnsureCoreWebView2Async(environment);

            var settings = _webView.CoreWebView2.Settings;
            settings.AreDefaultContextMenusEnabled = false;
            settings.AreDevToolsEnabled = false;
            settings.IsStatusBarEnabled = false;
            settings.IsZoomControlEnabled = true;

            _webView.CoreWebView2.NavigationStarting += (_, e) =>
            {
                if (!IsLocalRoofSpanUri(e.Uri))
                {
                    e.Cancel = true;
                    OpenExternal(e.Uri);
                }
            };

            _webView.CoreWebView2.NewWindowRequested += (_, e) =>
            {
                e.Handled = true;
                if (IsLocalRoofSpanUri(e.Uri))
                {
                    _webView.CoreWebView2.Navigate(e.Uri);
                }
                else
                {
                    OpenExternal(e.Uri);
                }
            };

            _webView.Source = LocalAppUri;
        }
        catch (Exception ex)
        {
            Controls.Clear();
            _status.Text = "RoofSpan Office could not start its local application window.\r\n\r\n" + ex.Message;
            Controls.Add(_status);
        }
    }

    private static bool IsLocalRoofSpanUri(string? value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri)) return false;
        return uri.Scheme == Uri.UriSchemeHttp && uri.Host == "127.0.0.1" && uri.Port == 8001;
    }

    private static void OpenExternal(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return;
        try
        {
            Process.Start(new ProcessStartInfo(value) { UseShellExecute = true });
        }
        catch { }
    }

    private static async Task<bool> WaitForBackendAsync(TimeSpan timeout)
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            try
            {
                using var response = await client.GetAsync(new Uri(LocalAppUri, "api/health"));
                if (response.IsSuccessStatusCode) return true;
            }
            catch { }
            await Task.Delay(1000);
        }
        return false;
    }
}
