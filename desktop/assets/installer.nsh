!include "FileFunc.nsh"

Var WebOBSUpdateTemp

; electron-builder's upgrade uninstaller atomically renames files into its
; plugin directory. Put that child's private TEMP on the existing install
; volume so upgrades also work when Windows TEMP is on another drive.
!macro customInit
  Push $0
  Push $1
  Push $2
  Push $3
  Push $4
  Push $5
  Push $6
  Push $7
  ReadRegStr $0 HKCU "${INSTALL_REGISTRY_KEY}" "InstallLocation"
  ${If} $0 != ""
  ${AndIf} ${FileExists} "$0\${APP_EXECUTABLE_FILENAME}"
    ${GetParent} "$0" $1
    GetTempFileName $2 "$1"
    Delete "$2"
    ${GetFileName} "$2" $2
    StrCpy $WebOBSUpdateTemp "$1\.WebOBS-update-$2"
    ClearErrors
    CreateDirectory "$WebOBSUpdateTemp"
    ${If} ${Errors}
      MessageBox MB_OK|MB_ICONSTOP "Cannot create the update directory beside the existing installation."
      Abort
    ${EndIf}
    ; Protected owner/system ACL, inherited by child installer files. This
    ; contains public program bytes only; account data remains in LOCALAPPDATA.
    System::Call 'advapi32::ConvertStringSecurityDescriptorToSecurityDescriptorW(w "D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)", i 1, *p .r3, p 0) i .r4'
    ${If} $4 != 0
      System::Call 'advapi32::GetSecurityDescriptorDacl(p r3, *i .r4, *p .r5, *i .r6) i .r7'
      ${If} $7 != 0
      ${AndIf} $4 != 0
        System::Call 'advapi32::SetNamedSecurityInfoW(w "$WebOBSUpdateTemp", i 1, i 0x80000004, p 0, p 0, p r5, p 0) i .r7'
        StrCpy $4 0
        ${If} $7 == 0
          StrCpy $4 1
        ${EndIf}
      ${Else}
        StrCpy $4 0
      ${EndIf}
      System::Call 'kernel32::LocalFree(p r3)'
    ${EndIf}
    ${If} $4 == 0
      MessageBox MB_OK|MB_ICONSTOP "Cannot protect the temporary update directory."
      Abort
    ${EndIf}
    System::Call 'kernel32::SetEnvironmentVariableW(w "TEMP", w "$WebOBSUpdateTemp") i .r4'
    ${If} $4 == 0
      Abort "Cannot set the temporary update directory."
    ${EndIf}
    System::Call 'kernel32::SetEnvironmentVariableW(w "TMP", w "$WebOBSUpdateTemp") i .r4'
    ${If} $4 == 0
      Abort "Cannot set the temporary update directory."
    ${EndIf}
  ${EndIf}
  Pop $7
  Pop $6
  Pop $5
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Pop $0
!macroend

!macro customInstall
  ${If} $WebOBSUpdateTemp != ""
    ; Remove only an empty directory owned by this installer. Child NSIS
    ; processes remove their own plugin files on exit; never recurse here.
    RMDir "$WebOBSUpdateTemp"
  ${EndIf}
!macroend
