param([switch]$Check, [switch]$DevTools)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Download-File($Url, $Path) {
    $downloadOptions = @{Uri=$Url; OutFile=$Path; UseBasicParsing=$true}
    if ($env:HTTPS_PROXY) { $downloadOptions.Proxy = $env:HTTPS_PROXY }
    Invoke-WebRequest @downloadOptions
}

function Ensure-WebView {
    # Enumerate product names because the WebView2 client GUID has varied by channel.
    $bases = @('HKCU:\Software\Microsoft\EdgeUpdate\Clients',
               'HKLM:\Software\Microsoft\EdgeUpdate\Clients',
               'HKLM:\Software\WOW6432Node\Microsoft\EdgeUpdate\Clients')
    foreach ($base in $bases) {
        if (Test-Path $base) {
            foreach ($key in Get-ChildItem $base) {
                $product = Get-ItemProperty $key.PSPath
                if ($product.name -like '*WebView2*' -and $product.pv -and $product.pv -ne '0.0.0.0') { return }
            }
        }
    }
    if ($Check) { throw 'WebView2 is missing. Run setup without -Check.' }
    Write-Host 'Installing Microsoft Edge WebView2 Runtime...'
    $installer = Join-Path $root 'cache\bootstrap\MicrosoftEdgeWebview2Setup.exe'
    Download-File 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' $installer
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation,') {
        throw 'WebView2 installer does not have a valid Microsoft signature.'
    }
    $process = Start-Process -FilePath $installer -ArgumentList '/silent','/install' -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -notin @(0,3010)) { throw "WebView2 installation failed: $($process.ExitCode)" }
}

try {
    if (![Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
        throw 'This release supports Windows x64 (Intel/AMD) only.'
    }
    $plan = Get-Content -LiteralPath (Join-Path $root 'scripts\install\windows-x64.json') -Raw | ConvertFrom-Json
    $boot = Join-Path $root 'cache\bootstrap'
    $uv = Join-Path $boot 'uv\uv.exe'
    $python = Join-Path $root 'runtimes\downloader\Scripts\python.exe'
    if ($Check) {
        if (!(Test-Path -LiteralPath $python)) { throw 'Environment missing. Run setup without -Check.' }
        Ensure-WebView
        & $python -X utf8 (Join-Path $root 'scripts\setup-runtime-windows.py') --uv $uv --check
        exit $LASTEXITCODE
    }
    New-Item -ItemType Directory -Force -Path $boot | Out-Null
    $archive = Join-Path $boot 'uv.zip'
    if (!(Test-Path -LiteralPath $archive)) {
        Write-Host 'Downloading the verified Python bootstrap tool...'
        Download-File $plan.uv.url ($archive+'.part')
        Move-Item -LiteralPath ($archive+'.part') -Destination $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $plan.uv.sha256) {
        throw 'uv checksum mismatch. Remove cache\bootstrap\uv.zip and retry.'
    }
    Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $boot 'uv') -Force
    # Always use the bootstrap Python: an existing venv may have moved with the installation.
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $boot 'python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $boot 'bin'
    $env:UV_CACHE_DIR = Join-Path $root 'cache\uv'
    $env:UV_NO_CONFIG = '1'
    & $uv python install $plan.python
    if ($LASTEXITCODE -ne 0) { throw 'Python bootstrap download failed.' }
    $bootstrapPython = Join-Path $env:UV_PYTHON_INSTALL_DIR ($plan.python+'\python.exe')
    Ensure-WebView
    $setupArgs = @('-X','utf8',(Join-Path $root 'scripts\setup-runtime-windows.py'),'--uv',$uv,'--apply')
    if ($DevTools) { $setupArgs += '--dev-tools' }
    & $bootstrapPython @setupArgs
    if ($LASTEXITCODE -ne 0) { throw 'Runtime installation/check failed. Downloaded files are retained.' }
    Write-Host 'Setup complete. Put the matching models and ScholarNoteLM.exe here, then open the app.'
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
