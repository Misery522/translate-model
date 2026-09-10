#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bridge;

use bridge::{ApiRequest, ApiResponse, BackendStatus, Bridge, BridgeError};
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{
    image::Image,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

struct HostState {
    bridge: Bridge,
    shortcut_available: AtomicBool,
    exiting: AtomicBool,
}

impl HostState {
    fn accepts_command(&self, label: &str) -> bool {
        label == "main" && !self.exiting.load(Ordering::SeqCst)
    }

    fn begin_exit(&self) -> bool {
        // 在异步撤销前同步关闭命令入口；重复点击退出不能启动第二轮撤销。
        !self.exiting.swap(true, Ordering::SeqCst)
    }
}

fn only_main(window: &tauri::WebviewWindow, state: &HostState) -> Result<(), BridgeError> {
    if state.accepts_command(window.label()) {
        Ok(())
    } else {
        Err(BridgeError::forbidden())
    }
}

#[tauri::command]
fn configure_backend(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, HostState>,
    origin: String,
) -> Result<BackendStatus, BridgeError> {
    only_main(&window, &state)?;
    state
        .bridge
        .configure(&origin, state.shortcut_available.load(Ordering::Relaxed))
}

#[tauri::command]
fn backend_status(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, HostState>,
) -> Result<BackendStatus, BridgeError> {
    only_main(&window, &state)?;
    state
        .bridge
        .status(state.shortcut_available.load(Ordering::Relaxed))
}

#[tauri::command]
async fn api_request(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, HostState>,
    request: serde_json::Value,
) -> Result<ApiResponse, BridgeError> {
    only_main(&window, &state)?;
    // 不把 serde 的详细错误返回前端，以免回显配对码或输入文本。
    let request: ApiRequest =
        serde_json::from_value(request).map_err(|_| BridgeError::invalid())?;
    state.bridge.request(request).await
}

fn show_main(app: &tauri::AppHandle) {
    if app.state::<HostState>().exiting.load(Ordering::SeqCst) {
        return;
    }
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn tray_icon() -> Image<'static> {
    // 原创像素对话气泡；仅显示标识，不读取截图或剪贴板。
    let mut pixels = vec![0_u8; 32 * 32 * 4];
    for y in 3..29 {
        for x in 3..29 {
            let eye = (10..13).contains(&x) || (20..23).contains(&x);
            let color = if eye && (11..15).contains(&y) {
                [255, 255, 255, 255]
            } else {
                [20, 130, 120, 255]
            };
            pixels[(y * 32 + x) * 4..(y * 32 + x) * 4 + 4].copy_from_slice(&color);
        }
    }
    Image::new_owned(pixels, 32, 32)
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let bridge = Bridge::new().map_err(|_| std::io::Error::other("安全连接初始化失败"))?;
    tauri::Builder::default()
        .manage(HostState {
            bridge,
            shortcut_available: AtomicBool::new(false),
            exiting: AtomicBool::new(false),
        })
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _, event| {
                    if event.state() == ShortcutState::Pressed {
                        show_main(app);
                    }
                })
                .build(),
        )
        .setup(|app| {
            let open = MenuItem::with_id(app, "show", "打开译境", true, None::<&str>)?;
            let hide = MenuItem::with_id(app, "hide", "隐藏宠物", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出译境", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &hide, &quit])?;
            // 托盘创建失败则启动失败，避免无边框隐藏窗口无法恢复。
            TrayIconBuilder::new()
                .icon(tray_icon())
                .tooltip("译境 · Ctrl+Shift+T 打开")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main(app),
                    "hide" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.hide();
                        }
                    }
                    "quit" => {
                        if app.state::<HostState>().begin_exit() {
                            let handle = app.clone();
                            tauri::async_runtime::spawn(async move {
                                // 仅最多三秒的尽力撤销；失败仍释放本地内存并退出。
                                let state = handle.state::<HostState>();
                                let _ = state.bridge.request(ApiRequest::Logout).await;
                                state.bridge.clear();
                                handle.exit(0);
                            });
                        }
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if matches!(
                        event,
                        TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            ..
                        }
                    ) {
                        show_main(tray.app_handle());
                    }
                })
                .build(app)?;
            let window_config = app
                .config()
                .app
                .windows
                .first()
                .ok_or_else(|| std::io::Error::other("缺少 main 窗口配置"))?;
            WebviewWindowBuilder::from_config(app, window_config)?
                .on_navigation(bridge::local_navigation_allowed)
                .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
                .build()?;
            // 快捷键冲突不应使应用无法启动；状态区域可提示仍能从托盘打开。
            let available = app.global_shortcut().register("Ctrl+Shift+T").is_ok();
            app.state::<HostState>()
                .shortcut_available
                .store(available, Ordering::Relaxed);
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            configure_backend,
            backend_status,
            api_request
        ])
        .run(tauri::generate_context!())?;
    Ok(())
}

fn main() {
    if run().is_err() {
        // 固定错误；不输出后台地址、系统路径、令牌或输入内容。
        eprintln!("译境桌面宿主启动失败，请检查 WebView2 与安装完整性。");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exit_closes_command_gate_before_cleanup_and_is_idempotent() {
        let state = HostState {
            bridge: Bridge::new().unwrap(),
            shortcut_available: AtomicBool::new(false),
            exiting: AtomicBool::new(false),
        };
        assert!(state.accepts_command("main"));
        assert!(!state.accepts_command("other"));
        assert!(state.begin_exit());
        assert!(!state.accepts_command("main"));
        assert!(!state.begin_exit());
        // 清除内存凭据也不能重新打开退出中的命令入口。
        state.bridge.clear();
        assert!(!state.accepts_command("main"));
    }
}
