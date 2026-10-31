; Unsigned per-user development installer for the frozen OBS-native prototype.
; It installs the already-verified prototype tree under %LOCALAPPDATA%, keeps the
; private portable profile in <install>\config across reinstall and uninstall,
; and writes only HKCU uninstall metadata. It registers no service and does not
; run the product at install time.
Unicode True
!include "MUI2.nsh"
!include "FileFunc.nsh"

!ifndef VERSION
  !define VERSION "0.0.0-dev.0"
!endif
!ifndef PACKAGE_DIR
  !error "PACKAGE_DIR is required (the verified prototype runtime tree)."
!endif
!ifndef OUTPUT_DIR
  !define OUTPUT_DIR "."
!endif

!define PRODUCT "WebOBS Native Prototype"
!define UNINST_ROOT "Software\Microsoft\Windows\CurrentVersion\Uninstall\WebOBSNativePrototype"
!define APP_ROOT "Software\WebOBS\NativePrototype"

Name "${PRODUCT} ${VERSION}"
OutFile "${OUTPUT_DIR}\WebOBS-OBS-native-${VERSION}-windows-x64-SETUP.exe"
InstallDir "$LOCALAPPDATA\WebOBS Native Prototype"
InstallDirRegKey HKCU "${APP_ROOT}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
ShowInstDetails show
ShowUninstDetails show
BrandingText "${PRODUCT} development build (unsigned)"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "${PACKAGE_DIR}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${APP_ROOT}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_ROOT}" "DisplayName" "${PRODUCT}"
  WriteRegStr HKCU "${UNINST_ROOT}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_ROOT}" "Publisher" "WebOBS development build"
  WriteRegStr HKCU "${UNINST_ROOT}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_ROOT}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINST_ROOT}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_ROOT}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_ROOT}" "EstimatedSize" $0
SectionEnd

Section "Uninstall"
  ; Everything except the private portable profile is owned by this installer.
  ; config\ may contain RTSP credentials and the five-tile wall, so it stays.
  FindFirst $0 $1 "$INSTDIR\*.*"
  un_loop:
    StrCmp $1 "" un_done
    StrCmp $1 "." un_next
    StrCmp $1 ".." un_next
    StrCmp $1 "config" un_next
    StrCmp $1 "Uninstall.exe" un_next
    IfFileExists "$INSTDIR\$1\*.*" 0 un_file
      RMDir /r "$INSTDIR\$1"
      Goto un_next
    un_file:
      Delete "$INSTDIR\$1"
    un_next:
    FindNext $0 $1
    Goto un_loop
  un_done:
  FindClose $0
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${APP_ROOT}"
  DeleteRegKey HKCU "${UNINST_ROOT}"
SectionEnd
