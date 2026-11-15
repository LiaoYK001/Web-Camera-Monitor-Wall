; Internal R1 integrated product gate. Never publishes or replaces legacy WebOBS.
Unicode True
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"
!ifndef VERSION
  !error "Verified development VERSION required."
!endif
!ifndef PACKAGE_DIR
  !error "Verified integrated product PACKAGE_DIR required."
!endif
!ifndef OUTPUT_DIR
  !error "New internal OUTPUT_DIR required."
!endif
!ifndef OWNED_REMOVALS
  !error "Verified owned-file uninstall include required."
!endif
!ifdef NATIVE_PREVIEW
  !define PRODUCT "WebOBS Wall v4.5 Preview"
  !define APP_ROOT "Software\WebOBS\WallPreview"
  !define UNINST_ROOT "Software\Microsoft\Windows\CurrentVersion\Uninstall\WebOBSWallPreview"
  OutFile "${OUTPUT_DIR}\WebOBS-Wall-${VERSION}-windows-x64-PREVIEW-UNSIGNED.exe"
  InstallDir "$LOCALAPPDATA\Programs\WebOBS Wall Preview"
  BrandingText "Native monitor preview - no automatic updates or legacy data migration"
!else
  !define PRODUCT "WebOBS Wall Integration"
  !define APP_ROOT "Software\WebOBS\WallIntegration"
  !define UNINST_ROOT "Software\Microsoft\Windows\CurrentVersion\Uninstall\WebOBSWallIntegration"
  OutFile "${OUTPUT_DIR}\WebOBS-Wall-${VERSION}-INTERNAL-SETUP.exe"
  InstallDir "$LOCALAPPDATA\Programs\WebOBS Wall Integration"
  BrandingText "Internal integration build - not a complete release"
!endif
Name "${PRODUCT} ${VERSION}"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
!insertmacro MUI_PAGE_WELCOME
!ifdef NATIVE_PREVIEW
  !insertmacro MUI_PAGE_LICENSE "${PACKAGE_DIR}\licenses\webobs-native\PLUGIN-COPYING.txt"
!endif
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ${IfNot} ${RunningX64}
    Abort "Windows x64 is required."
  ${EndIf}
  SetRegView 64
  SetShellVarContext current
  ReadRegStr $0 HKCU "${APP_ROOT}" "InstallDir"
  StrCmp $0 "" +2
    Abort "This installation already exists. Uninstall it first; private data is retained. Automatic upgrade is not enabled."
  IfFileExists "$SMPROGRAMS\${PRODUCT}.lnk" 0 +2
    Abort "The integration shortcut already exists. No existing shortcuts will be replaced."
FunctionEnd

Function un.onInit
  SetRegView 64
  SetShellVarContext current
  ReadRegStr $0 HKCU "${APP_ROOT}" "InstallDir"
  StrCmp $0 "$INSTDIR" +2
    Abort "The uninstall location does not match this integration installation."
FunctionEnd

Section "Integrated native product"
  ; R1 permits fresh isolated installation only. R4 owns qualified migration and
  ; upgrade; do not overwrite either legacy product data or arbitrary files.
  IfFileExists "$INSTDIR\*.*" 0 +2
    Abort "Choose a new installation directory."
  SetOutPath "$INSTDIR"
  File /r "${PACKAGE_DIR}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortCut "$SMPROGRAMS\${PRODUCT}.lnk" "$INSTDIR\bin\webobs-wall.exe"
  WriteRegStr HKCU "${APP_ROOT}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_ROOT}" "DisplayName" "${PRODUCT}"
  WriteRegStr HKCU "${UNINST_ROOT}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_ROOT}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_ROOT}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINST_ROOT}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_ROOT}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "${UNINST_ROOT}" "EstimatedSize" $0
SectionEnd

Section "Uninstall"
  ; Only verified payload files are removed. Private NativeIntegration data is
  ; outside INSTDIR and intentionally retained; unknown files are also retained.
  !include "${OWNED_REMOVALS}"
  Delete "$SMPROGRAMS\${PRODUCT}.lnk"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${APP_ROOT}"
  DeleteRegKey HKCU "${UNINST_ROOT}"
SectionEnd
