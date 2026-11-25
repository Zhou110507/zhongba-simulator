using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

internal static class Launcher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        try
        {
            StringBuilder arguments = new StringBuilder("-X utf8 -m billiards.launcher");
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--no-open")
                    arguments.Append(" --no-open");
                else if (args[i] == "--port" && i + 1 < args.Length)
                {
                    int port;
                    if (!int.TryParse(args[++i], out port) || port < 1 || port > 65535)
                        throw new ArgumentException("Choose a port between 1 and 65535.");
                    arguments.Append(" --port ").Append(port);
                }
                else
                    throw new ArgumentException("Supported options: --no-open and --port NUMBER.");
            }

            ProcessStartInfo info = new ProcessStartInfo(
                Path.Combine(root, "runtime", "python.exe"), arguments.ToString());
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardError = true;
            info.StandardErrorEncoding = Encoding.UTF8;
            using (Process launcher = Process.Start(info))
            {
                string error = launcher.StandardError.ReadToEnd();
                launcher.WaitForExit();
                if (launcher.ExitCode != 0)
                    throw new InvalidOperationException(error.Trim());
            }
            return 0;
        }
        catch (Exception failure)
        {
            string message = "中八球房未能启动。请将整个压缩包解压至可写文件夹。\n\n" + failure.Message;
            if (Array.IndexOf(args, "--no-open") < 0)
                MessageBox.Show(message, "中八球房", MessageBoxButtons.OK, MessageBoxIcon.Error);
            else
                Console.Error.WriteLine(message);
            return 1;
        }
    }
}
