; Build parameters are supplied by build-windows-standalone.py.
[Setup]
AppId={{B4D61E90-5341-4901-8747-F18171FA7E17}
AppName=ScholarNoteLM Standalone
AppVersion={#AppVersion}
AppVerName=ScholarNoteLM {#AppVersion} (Windows offline edition)
AppPublisher=ScholarNoteLM
AppPublisherURL=https://github.com/XinYu-pumch/ScholarNoteLM
DefaultDirName={localappdata}\ScholarNoteLM-Standalone
DefaultGroupName=ScholarNoteLM Standalone
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible and not arm64
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=ScholarNoteLM-{#AppVersion}-windows-x64-standalone-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\ScholarNoteLM-Standalone.exe
Compression=lzma2/normal
SolidCompression=yes
#ifdef BundleCuda
; CUDA plus the offline models exceeds Windows' single-EXE size limit.
DiskSpanning=yes
DiskSliceSize=max
#endif
LZMAUseSeparateProcess=yes
AppMutex=Local\ScholarNoteLMStandalone
CloseApplications=no
RestartApplications=no
SetupLogging=yes
LicenseFile={#PayloadDir}\app\LICENSE
InfoBeforeFile={#PayloadDir}\INSTALL-README.txt

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: checkedonce

[Files]
#include FilesList
Source: "{#WebViewInstaller}"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView

[Icons]
Name: "{group}\ScholarNoteLM Standalone"; Filename: "{app}\ScholarNoteLM-Standalone.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\ScholarNoteLM Standalone"; Filename: "{app}\ScholarNoteLM-Standalone.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Uninstall ScholarNoteLM Standalone"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\ScholarNoteLM-Standalone.exe"; Description: "Launch ScholarNoteLM"; Flags: nowait postinstall skipifsilent

[Code]
function HasWebViewAt(Root: Integer; Base: String): Boolean;
var Names: TArrayOfString; I: Integer; Name, Version: String;
begin
  Result := False;
  if RegGetSubkeyNames(Root, Base, Names) then
    for I := 0 to GetArrayLength(Names)-1 do
      if RegQueryStringValue(Root, Base+'\'+Names[I], 'name', Name) and
         RegQueryStringValue(Root, Base+'\'+Names[I], 'pv', Version) then
        if (Pos('webview2', Lowercase(Name))>0) and (Version<>'') and (Version<>'0.0.0.0') then
          Result := True;
end;

function NeedsWebView: Boolean;
begin
  Result := not (HasWebViewAt(HKCU, 'Software\Microsoft\EdgeUpdate\Clients') or
    HasWebViewAt(HKLM64, 'Software\Microsoft\EdgeUpdate\Clients') or
    HasWebViewAt(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  { Never overwrite a source checkout or an unrelated application's directory. }
  if DirExists(ExpandConstant('{app}')) and
     not FileExists(ExpandConstant('{app}\standalone-manifest.json')) then
    if DirExists(ExpandConstant('{app}\app')) or
       DirExists(ExpandConstant('{app}\services')) or
       DirExists(ExpandConstant('{app}\runtimes')) or
       FileExists(ExpandConstant('{app}\ScholarNoteLM.exe')) then
      Result := 'Choose a new folder for the standalone edition. Existing source installations are not overwritten.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer;
begin
  if CurStep=ssPostInstall then begin
    if NeedsWebView then begin
      if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'),
          '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code) then
        RaiseException('Could not start the bundled WebView2 offline installer.');
      if not NeedsWebView then Log('WebView2 is ready.')
      else RaiseException('WebView2 offline installation failed. Retry setup. Exit code: '+IntToStr(Code));
    end;
    if not Exec(ExpandConstant('{app}\ScholarNoteLM-Standalone.exe'), '--prepare',
        ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) then
      RaiseException('Could not initialize the offline runtime.');
    if Code<>0 then RaiseException('Offline runtime preparation failed. See app\tmp\standalone-launch.log.');
  end;
end;

{ No wildcard UninstallDelete entries: generated config/data/cache and research
  projects are preserved. Python homes are generated, never installed files. }
