// Standalone-only entry. The existing application executable/source remain unchanged.
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;

class StandaloneLauncher {
    const string MutexName = "Local\\ScholarNoteLMStandalone";
    static string Quote(string value) { return "\"" + value.Replace("\"", "\\\"") + "\""; }

    static ProcessStartInfo StartInfo(string executable, string arguments, string root) {
        var info = new ProcessStartInfo(executable, arguments) {
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        foreach (string key in new[] {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"})
            info.EnvironmentVariables.Remove(key);
        string windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        info.EnvironmentVariables["PATH"] = Path.Combine(root,"runtimes\\node") + ";" +
            Path.Combine(windows,"System32") + ";" + windows + ";" + Path.Combine(windows,"System32\\WindowsPowerShell\\v1.0");
        info.EnvironmentVariables["SCHOLARNOTELM_ROOT"] = root;
        info.EnvironmentVariables["PYTHONUTF8"] = "1";
        info.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
        info.EnvironmentVariables["PLAYWRIGHT_BROWSERS_PATH"] = Path.Combine(root,"runtimes\\playwright");
        info.EnvironmentVariables["WEBVIEW2_USER_DATA_FOLDER"] = Path.Combine(root,"cache\\webview2");
        foreach (string key in new[] {"TMP", "TEMP", "TMPDIR"}) info.EnvironmentVariables[key] = Path.Combine(root,"tmp");
        return info;
    }

    static int Run(ProcessStartInfo info, string log, int timeout) {
        using (var writer = new StreamWriter(log, true, new UTF8Encoding(false)))
        using (var child = new Process { StartInfo = info }) {
            writer.AutoFlush = true;
            object gate = new object();
            child.OutputDataReceived += (s,e) => { if(e.Data!=null) lock(gate) writer.WriteLine(e.Data); };
            child.ErrorDataReceived += (s,e) => { if(e.Data!=null) lock(gate) writer.WriteLine(e.Data); };
            child.Start(); child.BeginOutputReadLine(); child.BeginErrorReadLine();
            if(timeout>0 && !child.WaitForExit(timeout)) { child.Kill(); throw new Exception("初始化超时，请查看日志。"); }
            child.WaitForExit(); return child.ExitCode;
        }
    }

    [STAThread]
    static int Main(string[] args) {
        bool check = Array.IndexOf(args,"--check")>=0;
        bool prepare = Array.IndexOf(args,"--prepare")>=0;
        bool quiet = check || prepare;
        string root = Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"app");
        string log = Path.Combine(root,"tmp",check ? "standalone-check.log" : "standalone-launch.log");
        try {
            if(args.Length>1 || (args.Length==1 && !quiet)) throw new Exception("Unsupported argument.");
            bool acquired;
            using(var mutex = new Mutex(true,MutexName,out acquired)) {
                if(!acquired) throw new Exception("独立版正在运行。请先退出，再启动或检查环境。");
                if(!Environment.Is64BitOperatingSystem || Environment.GetEnvironmentVariable("PROCESSOR_ARCHITECTURE")=="ARM64")
                    throw new Exception("此版本仅支持 Windows x64（Intel/AMD）。");
                Directory.CreateDirectory(Path.Combine(root,"tmp"));
                File.WriteAllText(log,DateTime.UtcNow.ToString("o")+Environment.NewLine,new UTF8Encoding(false));
                string python = Path.Combine(root,"runtimes\\python\\cpython-3.12.9-windows-x86_64-none\\python.exe");
                string script = Path.Combine(root,"scripts\\standalone\\bootstrap.py");
                int code = Run(StartInfo(python,"-I -S " + Quote(script) + " --root " + Quote(root) + (check ? " --check" : ""),root),log,check?600000:60000);
                if(code!=0) throw new Exception("离线环境初始化失败。请检查安装完整性，或重新安装。\n日志："+log);
                if(quiet) return 0;
                code = Run(StartInfo(Path.Combine(root,"ScholarNoteLM.exe"),"",root),log,0);
                if(code!=0) throw new Exception("应用异常退出。\n日志："+log);
                return 0;
            }
        } catch(Exception error) {
            try { File.AppendAllText(log,error.ToString()+Environment.NewLine,new UTF8Encoding(false)); } catch { }
            if(!quiet) MessageBox.Show(error.Message,"ScholarNoteLM 独立版",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        }
    }
}
