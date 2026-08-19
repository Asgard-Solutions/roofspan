using System;
using System.Threading;
using System.Windows.Forms;

namespace RoofSpanOffice
{
    internal static class Program
    {
        // Registered (system-wide, uniquely-named) window message used to foreground an already-running
        // instance. RegisterWindowMessage returns the SAME id for the same string in every process.
        public static readonly int WM_SHOW_ROOFSPAN =
            NativeMethods.RegisterWindowMessage("RoofSpanOffice.ShowExistingInstance");

        [STAThread]
        private static void Main()
        {
            // Single-instance (per interactive user session). If RoofSpan Office is already open, ask that
            // existing window to come to the foreground and exit THIS launch - never start a second shell,
            // never kill the healthy running one.
            bool createdNew;
            using (var mutex = new Mutex(true, @"Local\RoofSpanOffice.SingleInstance", out createdNew))
            {
                if (!createdNew)
                {
                    NativeMethods.PostMessage(NativeMethods.HWND_BROADCAST, WM_SHOW_ROOFSPAN, IntPtr.Zero, IntPtr.Zero);
                    return;
                }

                ApplicationConfiguration.Initialize();
                Application.Run(new ShellForm());
                GC.KeepAlive(mutex);
            }
        }
    }
}
