// Small .NET Framework bootstrap UI; does not require Python, Node or WebView2.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

class SetupForm : Form {
    readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    readonly TextBox log = new TextBox();
    readonly Button install = new Button();
    readonly Button check = new Button();
    readonly Button open = new Button();
    readonly CheckBox dev = new CheckBox();
    readonly CheckBox cuda = new CheckBox();
    Process process;
    bool running;

    public SetupForm() {
        Text = "ScholarNoteLM · 环境安装";
        ClientSize = new Size(800, 570);
        MinimumSize = new Size(650, 480);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 10);
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(20), ColumnCount = 1, RowCount = 6 };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 70));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 50));
        layout.Controls.Add(new Label { Dock = DockStyle.Fill, Text = "安装 ScholarNoteLM 所需的独立 Python、Node 和浏览器环境。\n首次安装需要网络；模型文件请放入此目录的 models 文件夹。", AutoSize = false }, 0, 0);
        layout.Controls.Add(new Label { Dock = DockStyle.Fill, Text = root, AutoEllipsis = true }, 0, 1);
        log.Multiline = true; log.ReadOnly = true; log.ScrollBars = ScrollBars.Both;
        log.WordWrap = false; log.Dock = DockStyle.Fill; log.Font = new Font("Consolas", 9);
        layout.Controls.Add(log, 0, 2);
        dev.Text = "开发工具：额外安装 Rust 和前端依赖（普通使用无需勾选）";
        dev.AutoSize = true; layout.Controls.Add(dev, 0, 3);
        cuda.Text = "自动安装 NVIDIA CUDA 加速（适用显卡额外下载约 2–3 GB；保留 CPU）";
        cuda.Checked = true; cuda.AutoSize = true; layout.Controls.Add(cuda, 0, 4);
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight };
        install.Text = "安装 / 继续"; check.Text = "检查环境"; open.Text = "启动应用";
        foreach (var b in new[] { install, check, open }) { b.Width = 140; b.Height = 36; buttons.Controls.Add(b); }
        install.Click += delegate { Start(false); };
        check.Click += delegate { Start(true); };
        open.Click += delegate {
            var exe = Path.Combine(root, "ScholarNoteLM.exe");
            if (!File.Exists(exe)) { MessageBox.Show("请先把同一 Release 的 ScholarNoteLM.exe 放到源码目录。", Text); return; }
            Process.Start(new ProcessStartInfo(exe) { WorkingDirectory = root, UseShellExecute = true });
        };
        layout.Controls.Add(buttons, 0, 5); Controls.Add(layout);
        FormClosing += delegate(object sender, FormClosingEventArgs e) {
            if (running) { e.Cancel = true; MessageBox.Show("安装正在进行，请等待完成。下载和安装日志会显示在窗口中。", Text); }
        };
    }

    void Append(string text) {
        if (text == null || IsDisposed) return;
        BeginInvoke((Action)(() => { log.AppendText(text + Environment.NewLine); }));
    }

    void Start(bool checking) {
        var script = Path.Combine(root, "scripts", "install-windows.ps1");
        if (!File.Exists(script) || !File.Exists(Path.Combine(root, "services", "downloader", "engine.py"))) {
            MessageBox.Show("请把本引导程序放到完整 ScholarNoteLM 源码目录中，然后重新打开。", Text); return;
        }
        install.Enabled = check.Enabled = open.Enabled = dev.Enabled = cuda.Enabled = false;
        running = true; log.Clear();
        var info = new ProcessStartInfo("powershell.exe", "-NoLogo -NoProfile -ExecutionPolicy Bypass -File \"" + script + "\"" + (checking ? " -Check" : (dev.Checked ? " -DevTools" : "") + (cuda.Checked ? "" : " -CpuOnly")));
        info.WorkingDirectory = root; info.UseShellExecute = false; info.CreateNoWindow = true;
        info.RedirectStandardOutput = info.RedirectStandardError = true;
        info.StandardOutputEncoding = info.StandardErrorEncoding = Encoding.UTF8;
        process = new Process { StartInfo = info, EnableRaisingEvents = true };
        process.OutputDataReceived += (s, e) => Append(e.Data);
        process.ErrorDataReceived += (s, e) => Append(e.Data);
        process.Exited += delegate {
            int code = process.ExitCode;
            BeginInvoke((Action)(() => {
                running = false; install.Enabled = check.Enabled = open.Enabled = dev.Enabled = cuda.Enabled = true;
                log.AppendText(Environment.NewLine + (code == 0 ? "完成。请确认模型和主程序已放入安装目录。" : "未完成。请处理上方错误，然后再次点击“安装 / 继续”。"));
            }));
        };
        try { process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine(); }
        catch (Exception error) {
            running = false; install.Enabled = check.Enabled = open.Enabled = dev.Enabled = cuda.Enabled = true;
            log.AppendText(error.Message);
        }
    }

    [STAThread]
    static void Main() {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new SetupForm());
    }
}
