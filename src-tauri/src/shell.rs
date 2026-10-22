//! Window shell: splash screen hand-off and the tray icon. The main window starts hidden behind the splash and is shown
//! when the UI reports it has booted (or after a timeout, so a UI error never leaves the app invisible).
use std::time::{Duration, Instant};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::image::Image;
use tauri::{AppHandle, Manager, Runtime};

/// the splash stays at least this long, so it reads as a splash and not as a flicker
const MIN_SPLASH: Duration = Duration::from_millis(1600);
const MAX_SPLASH: Duration = Duration::from_secs(12);

pub struct Started(pub Instant);

pub fn show_main<R: Runtime>(app: &AppHandle<R>) {
    if let Some(w) = app.get_webview_window("main") {
        // show() alone does not bring back a minimized window on Windows
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
    if let Some(s) = app.get_webview_window("splash") {
        let _ = s.close();
    }
}

/// called by the UI once its first render is done
#[tauri::command]
pub async fn app_ready(app: AppHandle, started: tauri::State<'_, Started>) -> Result<(), String> {
    let wait = MIN_SPLASH.saturating_sub(started.0.elapsed());
    tokio::time::sleep(wait).await;
    show_main(&app);
    Ok(())
}

pub fn setup<R: Runtime>(app: &tauri::App<R>) -> tauri::Result<()> {
    app.manage(Started(Instant::now()));
    for label in ["main", "splash"] {
        if let Some(w) = app.get_webview_window(label) {
            set_big_icon(&w);
        }
    }
    let h = app.handle().clone();
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(MAX_SPLASH).await;
        if h.get_webview_window("main").is_some_and(|w| !w.is_visible().unwrap_or(true)) {
            show_main(&h);
        }
    });

    let show = MenuItem::with_id(app, "show", "Show Fumika", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &quit])?;
    let mut tray = TrayIconBuilder::with_id("main").tooltip("Fumika").menu(&menu).show_menu_on_left_click(false)
        .on_menu_event(|app, ev| match ev.id.as_ref() {
            "show" => show_main(app),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, ev| {
            if !matches!(ev, TrayIconEvent::Move { .. }) { eprintln!("[tray] {ev:?}"); }
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = ev {
                show_main(tray.app_handle());
            }
        });
    // own tray variant (page without the ink tile): the app icon's dark tile disappears on a dark taskbar
    match Image::from_bytes(include_bytes!("../icons/tray.png")) {
        Ok(icon) => tray = tray.icon(icon),
        Err(_) => if let Some(icon) = app.default_window_icon() { tray = tray.icon(icon.clone()); },
    }
    tray.build(app)?;
    Ok(())
}

/// tray menu in the UI language (the web view sends the labels when the language is applied)
#[tauri::command]
pub fn tray_labels(app: AppHandle, show: String, quit: String) -> Result<(), String> {
    let Some(t) = app.tray_by_id("main") else { return Ok(()) };
    let show = MenuItem::with_id(&app, "show", show, true, None::<&str>).map_err(|e| e.to_string())?;
    let quit = MenuItem::with_id(&app, "quit", quit, true, None::<&str>).map_err(|e| e.to_string())?;
    let menu = Menu::with_items(&app, &[&show, &quit]).map_err(|e| e.to_string())?;
    t.set_menu(Some(menu)).map_err(|e| e.to_string())
}

/// tray tooltip while a page is drawing, e.g. "Fumika · v2 · 31/50"
pub fn tray_status<R: Runtime>(app: &AppHandle<R>, status: Option<String>) {
    if let Some(t) = app.tray_by_id("main") {
        let text = status.map(|s| format!("Fumika · {s}")).unwrap_or_else(|| "Fumika".into());
        let _ = t.set_tooltip(Some(text));
    }
}

/// The large window icon (taskbar, Alt+Tab) from the exe's own icon resource. Tauri only sets the small one; without a large
/// icon the taskbar falls back to its icon cache, which keeps an older exe's icon at the same path even after a reinstall.
#[cfg(windows)]
fn set_big_icon<R: Runtime>(w: &tauri::WebviewWindow<R>) {
    use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
    use windows_sys::Win32::UI::WindowsAndMessaging::{GetSystemMetrics, LoadImageW, SendMessageW, ICON_BIG, IMAGE_ICON, LR_DEFAULTCOLOR, SM_CXICON, WM_SETICON};
    let Ok(hwnd) = w.hwnd() else { return };
    unsafe {
        // 2x the system's large icon size: the taskbar scales it down cleanly on high-DPI screens
        let size = (GetSystemMetrics(SM_CXICON).max(32) * 2).min(256);
        let icon = LoadImageW(GetModuleHandleW(std::ptr::null()), 32512 as _, IMAGE_ICON, size, size, LR_DEFAULTCOLOR);
        if !icon.is_null() {
            SendMessageW(hwnd.0 as _, WM_SETICON, ICON_BIG as usize, icon as isize);
        }
    }
}

#[cfg(not(windows))]
fn set_big_icon<R: Runtime>(_w: &tauri::WebviewWindow<R>) {}
