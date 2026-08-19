using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace RoofSpanOffice
{
    // The RoofSpan Office desktop window: a hardened Edge WebView2 host for the LOCAL Office web UI.
    public sealed class ShellForm : Form
    {
        private static readonly Color Backdrop = Color.FromArgb(15, 23, 42);   // slate-900, avoids white flash
        private static readonly Color Muted = Color.FromArgb(148, 163, 184);
        private static readonly Color Danger = Color.FromArgb(248, 113, 113);

        private readonly WebView2 _webView = new WebView2 { Dock = DockStyle.Fill, Visible = false };
        private readonly Panel _statusPanel = new Panel { Dock = DockStyle.Fill };
        private Label _statusText;
        private ProgressBar _progress;
        private FlowLayoutPanel _errorActions;

        private readonly HttpClient _http = new HttpClient
        {
            // Per-probe timeout is enforced via a linked CancellationTokenSource in WaitForBackendAsync, so
            // the HttpClient's own timeout is disabled to keep the overall deadline authoritative.
            Timeout = Timeout.InfiniteTimeSpan
        };
        private readonly Uri _baseUri = AppConfig.BaseUri();
        private CancellationTokenSource _cts = new CancellationTokenSource();
        private bool _coreReady;

        public ShellForm()
        {
            Text = AppConfig.WindowTitle;
            MinimumSize = new Size(1024, 700);
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(1280, 820);
            BackColor = Backdrop;
            try { Icon = LoadAppIcon(); } catch { /* default icon */ }

            BuildStatusPanel();
            Controls.Add(_webView);
            Controls.Add(_statusPanel);   // status panel on top until the UI is ready

            RestoreWindowState();

            Load += async (s, e) => await StartAsync();
            FormClosing += (s, e) => { SaveWindowState(); _cts.Cancel(); };
        }

        // ---- Startup / backend readiness -------------------------------------------------------------
        private async Task StartAsync()
        {
            ShowStarting();
            var ready = await WaitForBackendAsync(_cts.Token);
            if (_cts.IsCancellationRequested) return;   // user closed the window during startup
            if (!ready)
            {
                ShowBackendError();   // overall readiness deadline expired
                return;
            }
            await InitializeWebViewAsync();
        }

        private async Task<bool> WaitForBackendAsync(CancellationToken ct)
        {
            var url = AppConfig.HealthUrl();
            // Real OVERALL deadline: link the caller's token with a timer that fires after the overall
            // readiness timeout. The loop below can never materially exceed this, regardless of how long
            // individual probes take.
            using (var deadlineCts = CancellationTokenSource.CreateLinkedTokenSource(ct))
            {
                deadlineCts.CancelAfter(AppConfig.ReadinessOverallTimeout);
                var token = deadlineCts.Token;
                while (!token.IsCancellationRequested)
                {
                    try
                    {
                        // Bound EACH probe with its own short timeout (still capped by the overall deadline).
                        using (var reqCts = CancellationTokenSource.CreateLinkedTokenSource(token))
                        {
                            reqCts.CancelAfter(AppConfig.HealthRequestTimeout);
                            using (var resp = await _http.GetAsync(url, reqCts.Token))
                            {
                                if (resp.IsSuccessStatusCode) return true;   // stop immediately when healthy
                            }
                        }
                    }
                    catch { /* not up yet / probe timed out - keep trying until the overall deadline */ }

                    try { await Task.Delay(AppConfig.ReadinessDelayMs, token); }
                    catch (OperationCanceledException) { break; }
                }
            }
            return false;   // deadline (or user close) reached without a healthy backend
        }

        // ---- WebView2 host ---------------------------------------------------------------------------
        private async Task InitializeWebViewAsync()
        {
            try
            {
                if (!_coreReady)
                {
                    var env = await CoreWebView2Environment.CreateAsync(null, AppConfig.WebView2UserDataFolder(), null);
                    _webView.DefaultBackgroundColor = Backdrop;
                    await _webView.EnsureCoreWebView2Async(env);

                    var core = _webView.CoreWebView2;
                    HardenSettings(core);
                    core.NavigationStarting += OnNavigationStarting;
                    core.NewWindowRequested += OnNewWindowRequested;
                    core.WindowCloseRequested += (s, e) => BeginInvoke((Action)Close);
                    _coreReady = true;
                }

                _webView.NavigationCompleted -= OnFirstNavigationCompleted;
                _webView.NavigationCompleted += OnFirstNavigationCompleted;
                // Navigate to the application ROOT (not /login): the existing React/backend setup-gate
                // decides setup vs login vs authenticated Office (preserves first-run + Create account).
                _webView.CoreWebView2.Navigate(AppConfig.BaseUrl());
            }
            catch
            {
                ShowDisplayError();   // WebView2 environment/runtime init or navigation setup failed
            }
        }

        private static void HardenSettings(CoreWebView2 core)
        {
            var s = core.Settings;
            s.AreDevToolsEnabled = false;             // production: no DevTools
            s.IsStatusBarEnabled = false;             // no browser status bar (hides link URLs / "127.0.0.1")
            s.IsPasswordAutosaveEnabled = false;      // the shell must NOT store RoofSpan passwords
            s.IsGeneralAutofillEnabled = false;       // no browser autofill of PII in the shell
            s.IsSwipeNavigationEnabled = false;       // no back/forward swipe (this is an app, not a browser)
            // Kept ENABLED intentionally for a data-entry business app: default context menus (cut/copy/
            // paste), browser accelerator keys (Ctrl+P to print invoices, Ctrl+C/V/F), and zoom (a11y).
            s.AreDefaultContextMenusEnabled = true;
            s.AreBrowserAcceleratorKeysEnabled = true;
            s.IsZoomControlEnabled = true;
        }

        private void OnFirstNavigationCompleted(object sender, CoreWebView2NavigationCompletedEventArgs e)
        {
            _webView.NavigationCompleted -= OnFirstNavigationCompleted;
            if (e.IsSuccess)
            {
                _statusPanel.Visible = false;
                _webView.Visible = true;
                _webView.Focus();
            }
            else
            {
                // WebView2 initialized fine but the local page did not load -> treat as a backend/page issue.
                ShowBackendError();
            }
        }

        // ---- Navigation policy: keep RoofSpan Office in-app; external links open in the system browser --
        private bool IsInternal(string uri)
        {
            if (!Uri.TryCreate(uri, UriKind.Absolute, out var u)) return false;
            if (u.Scheme != Uri.UriSchemeHttp && u.Scheme != Uri.UriSchemeHttps) return false;
            return string.Equals(u.Host, _baseUri.Host, StringComparison.OrdinalIgnoreCase)
                   && u.Port == _baseUri.Port;
        }

        private void OnNavigationStarting(object sender, CoreWebView2NavigationStartingEventArgs e)
        {
            if (IsInternal(e.Uri)) return;
            // External destination (Stripe, roofspan.io, docs, mailto:, etc.): do NOT let it replace the
            // Office window - cancel and hand it to the user's default browser/mail client.
            e.Cancel = true;
            OpenExternal(e.Uri);
        }

        private void OnNewWindowRequested(object sender, CoreWebView2NewWindowRequestedEventArgs e)
        {
            // No popup WebView windows. Internal target -> navigate the main window; external -> system browser.
            e.Handled = true;
            if (IsInternal(e.Uri)) _webView.CoreWebView2.Navigate(e.Uri);
            else OpenExternal(e.Uri);
        }

        private static void OpenExternal(string uri)
        {
            try
            {
                if (!Uri.TryCreate(uri, UriKind.Absolute, out var u)) return;
                if (u.Scheme == Uri.UriSchemeHttp || u.Scheme == Uri.UriSchemeHttps || u.Scheme == "mailto")
                    Process.Start(new ProcessStartInfo(uri) { UseShellExecute = true });
                // Any other scheme (file:, javascript:, custom) is intentionally ignored for safety.
            }
            catch { /* never crash the shell on a bad external link */ }
        }

        // ---- Single-instance activation --------------------------------------------------------------
        protected override void WndProc(ref Message m)
        {
            if (Program.WM_SHOW_ROOFSPAN != 0 && m.Msg == Program.WM_SHOW_ROOFSPAN)
                BringToForeground();
            base.WndProc(ref m);
        }

        private void BringToForeground()
        {
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Show();
            Activate();
            NativeMethods.SetForegroundWindow(Handle);
        }

        // ---- Branded startup / error UI --------------------------------------------------------------
        private void BuildStatusPanel()
        {
            _statusPanel.BackColor = Backdrop;
            var center = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                BackColor = Backdrop,
                ColumnCount = 1,
                RowCount = 1
            };

            var stack = new FlowLayoutPanel
            {
                AutoSize = true,
                FlowDirection = FlowDirection.TopDown,
                WrapContents = false,
                Anchor = AnchorStyles.None,
                BackColor = Backdrop
            };

            var logo = new PictureBox
            {
                SizeMode = PictureBoxSizeMode.Zoom,
                Size = new Size(96, 96),
                Margin = new Padding(0, 0, 0, 16),
                Anchor = AnchorStyles.None
            };
            try { logo.Image = LoadAppIcon().ToBitmap(); } catch { }

            var title = new Label
            {
                Text = "RoofSpan Office",
                AutoSize = true,
                ForeColor = Color.White,
                Font = new Font("Segoe UI", 20F, FontStyle.Bold),
                Margin = new Padding(0, 0, 0, 8),
                Anchor = AnchorStyles.None
            };

            _statusText = new Label
            {
                Text = "Starting RoofSpan Office...",
                AutoSize = true,
                MaximumSize = new Size(420, 0),
                ForeColor = Muted,
                Font = new Font("Segoe UI", 11F),
                TextAlign = ContentAlignment.MiddleCenter,
                Margin = new Padding(0, 0, 0, 16),
                Anchor = AnchorStyles.None
            };

            _progress = new ProgressBar
            {
                Style = ProgressBarStyle.Marquee,
                MarqueeAnimationSpeed = 30,
                Width = 260,
                Height = 6,
                Anchor = AnchorStyles.None
            };

            _errorActions = new FlowLayoutPanel
            {
                AutoSize = true,
                FlowDirection = FlowDirection.LeftToRight,
                WrapContents = false,
                Visible = false,
                Margin = new Padding(0, 16, 0, 0),
                Anchor = AnchorStyles.None,
                BackColor = Backdrop
            };
            var retry = new Button { Text = "Retry", Width = 120, Height = 36, Margin = new Padding(0) };
            retry.Click += (s, e) => OnRetry();
            var close = new Button { Text = "Close", Width = 120, Height = 36, Margin = new Padding(12, 0, 0, 0) };
            close.Click += (s, e) => Close();
            _errorActions.Controls.Add(retry);
            _errorActions.Controls.Add(close);

            stack.Controls.Add(logo);
            stack.Controls.Add(title);
            stack.Controls.Add(_statusText);
            stack.Controls.Add(_progress);
            stack.Controls.Add(_errorActions);
            center.Controls.Add(stack, 0, 0);
            _statusPanel.Controls.Add(center);
        }

        private void OnRetry()
        {
            _cts = new CancellationTokenSource();
            _ = StartAsync();
        }

        private void ShowStarting()
        {
            _statusPanel.Visible = true;
            _webView.Visible = false;
            _progress.Visible = true;
            _errorActions.Visible = false;
            _statusText.ForeColor = Muted;
            SetStatus("Starting RoofSpan Office...");
        }

        private void SetStatus(string msg)
        {
            if (InvokeRequired) { BeginInvoke((Action)(() => _statusText.Text = msg)); return; }
            _statusText.Text = msg;
        }

        // Two DISTINCT, customer-safe failure states. Neither surfaces exception text, stack traces, file
        // paths, secrets, configuration, JWT, or database details - only a fixed headline + fixed detail.
        private void ShowBackendError()
        {
            ShowFailure(
                "RoofSpan Office could not connect to the local RoofSpan service.",
                "The local RoofSpan service did not become ready. Make sure RoofSpan is running, then try again.");
        }

        private void ShowDisplayError()
        {
            ShowFailure(
                "RoofSpan Office could not start its desktop display.",
                "The Microsoft Edge WebView2 Runtime could not be initialized. Reinstall RoofSpan (or the Microsoft Edge WebView2 Runtime), then try again.");
        }

        private void ShowFailure(string headline, string detail)
        {
            if (InvokeRequired) { BeginInvoke((Action)(() => ShowFailure(headline, detail))); return; }
            _statusPanel.Visible = true;
            _webView.Visible = false;
            _progress.Visible = false;
            _statusText.ForeColor = Danger;
            _statusText.Text = headline + "\n\n" + detail;
            _errorActions.Visible = true;   // Retry / Close
        }

        private static Icon LoadAppIcon()
        {
            var asm = typeof(ShellForm).Assembly;
            using (var s = asm.GetManifestResourceStream("RoofSpanOffice.ico"))
            {
                return s != null ? new Icon(s) : SystemIcons.Application;
            }
        }

        // ---- Window size/position persistence (best-effort) ------------------------------------------
        private sealed class SavedBounds
        {
            public int X { get; set; }
            public int Y { get; set; }
            public int W { get; set; }
            public int H { get; set; }
            public bool Max { get; set; }
        }

        private void SaveWindowState()
        {
            try
            {
                var b = (WindowState == FormWindowState.Normal) ? Bounds : RestoreBounds;
                var st = new SavedBounds
                {
                    X = b.X, Y = b.Y, W = b.Width, H = b.Height,
                    Max = (WindowState == FormWindowState.Maximized)
                };
                File.WriteAllText(AppConfig.WindowStateFile(), JsonSerializer.Serialize(st));
            }
            catch { }
        }

        private void RestoreWindowState()
        {
            try
            {
                var path = AppConfig.WindowStateFile();
                if (!File.Exists(path)) return;
                var st = JsonSerializer.Deserialize<SavedBounds>(File.ReadAllText(path));
                if (st == null || st.W < MinimumSize.Width || st.H < MinimumSize.Height) return;
                var rect = new Rectangle(st.X, st.Y, st.W, st.H);
                if (!IsOnAnyScreen(rect)) return;   // ignore off-screen positions (unplugged monitor, etc.)
                StartPosition = FormStartPosition.Manual;
                Bounds = rect;
                if (st.Max) WindowState = FormWindowState.Maximized;
            }
            catch { }
        }

        private static bool IsOnAnyScreen(Rectangle r)
        {
            foreach (var sc in Screen.AllScreens)
                if (sc.WorkingArea.IntersectsWith(r)) return true;
            return false;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _cts?.Cancel();
                _http?.Dispose();
                _webView?.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
