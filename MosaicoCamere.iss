; Script Inno Setup - Mosaico Camere (usato da Crea_Installer.bat)
#define AppName "Mosaico Camere"
#define AppVersion "1.0"
#define AppPublisher "Murari Nicola"
#define AppExe "MosaicoCamere.exe"

[Setup]
AppId={{7E3C1B52-9A4D-4F60-8B21-5D2A6C90E1F4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=Copyright (C) 2026 {#AppPublisher}
VersionInfoVersion=1.0.0.0
VersionInfoProductVersion=1.0.0.0
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} - Installazione
VersionInfoCopyright=Copyright (C) 2026 {#AppPublisher}
DefaultDirName={autopf}\MosaicoCamere
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer_out
OutputBaseFilename=Setup_MosaicoCamere_{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=CONDIZIONI_USO.txt
AppMutex=MosaicoCamereAppMutex
UninstallDisplayIcon={app}\{#AppExe}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Messages]
italian.WelcomeLabel2=Verra' installato [name/ver], creato da {#AppPublisher}.%n%nSi consiglia di chiudere le altre applicazioni prima di continuare.

[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento sul Desktop"; GroupDescription: "Collegamenti:"
Name: "ffmpeg"; Description: "Installa ffmpeg (serve per registrare in alta definizione)"; GroupDescription: "Componenti opzionali:"; Check: WingetOk

[Files]
Source: "dist\MosaicoCamere\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "CONDIZIONI_USO.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\Condizioni d'uso e licenza"; Filename: "{app}\CONDIZIONI_USO.txt"
Name: "{autoprograms}\Disinstalla {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{cmd}"; Parameters: "/C winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements"; StatusMsg: "Installazione di ffmpeg (1-2 minuti)..."; Flags: runhidden waituntilterminated; Tasks: ffmpeg
Filename: "{app}\{#AppExe}"; Description: "Avvia {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function WingetOk: Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Microsoft\WindowsApps\winget.exe'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if not UninstallSilent then
    begin
      if MsgBox('Vuoi eliminare anche le impostazioni e le telecamere salvate?' + #13#10 +
                '(Le registrazioni video NON vengono toccate.)',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(ExpandConstant('{userappdata}\MosaicoCamere'), True, True, True);
    end;
  end;
end;
