; Fumika NSIS hooks (tauri.conf.json bundle.windows.nsis.installerHooks)

!macro NSIS_HOOK_POSTUNINSTALL
  ; the installer remembers the last install folder here - without this a reinstall proposes the deleted folder
  DeleteRegKey HKCU "Software\7err4\Fumika"
  DeleteRegKey /ifempty HKCU "Software\7err4"
!macroend
