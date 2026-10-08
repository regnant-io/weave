!macro customInit
  SetShellVarContext current
!macroend

!macro customInstall
  WriteRegStr HKCU "Software\Weave" "LocalDataPath" "$APPDATA\Weave\data"
!macroend

!macro customUnInstall
  DeleteRegKey HKCU "Software\Weave"
!macroend
