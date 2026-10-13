// TriCloud 桌面客户端：本地只保存面板地址，窗口直接加载你自己的面板。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindowBuilder};

fn cfg_path(app: &AppHandle) -> Option<std::path::PathBuf> {
    app.path().app_config_dir().ok().map(|d| d.join("config.json"))
}

fn load_url(app: &AppHandle) -> Option<String> {
    let s = fs::read_to_string(cfg_path(app)?).ok()?;
    let v: serde_json::Value = serde_json::from_str(&s).ok()?;
    v.get("url")?.as_str().map(|s| s.to_string())
}

fn local_page() -> Url {
    let base = if cfg!(windows) { "http://tauri.localhost/index.html?setup=1" } else { "tauri://localhost/index.html?setup=1" };
    Url::parse(base).unwrap()
}

#[tauri::command]
fn get_url(app: AppHandle) -> Option<String> {
    load_url(&app)
}

#[tauri::command]
fn open_panel(app: AppHandle, url: String) -> Result<(), String> {
    let mut s = url.trim().to_string();
    if !s.contains("://") {
        s = format!("https://{}", s);
    }
    let u = Url::parse(&s).map_err(|_| "地址格式不对".to_string())?;
    if u.scheme() != "http" && u.scheme() != "https" {
        return Err("只支持 http:// 或 https:// 地址".into());
    }
    let p = cfg_path(&app).ok_or("找不到配置目录")?;
    if let Some(d) = p.parent() {
        fs::create_dir_all(d).map_err(|e| e.to_string())?;
    }
    fs::write(&p, serde_json::json!({ "url": u.as_str() }).to_string()).map_err(|e| e.to_string())?;
    let w = app.get_webview_window("main").ok_or("窗口不存在")?;
    w.navigate(u).map_err(|e| e.to_string())
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_url, open_panel])
        .setup(|app| {
            let h = app.handle().clone();
            let reload = MenuItem::with_id(&h, "reload", "刷新", true, Some("F5"))?;
            let home = MenuItem::with_id(&h, "home", "回到面板首页", true, None::<&str>)?;
            let change = MenuItem::with_id(&h, "change", "更换面板地址…", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(&h)?;
            let quit = PredefinedMenuItem::quit(&h, Some("退出"))?;
            let sub = Submenu::with_items(&h, "面板", true, &[&reload, &home, &change, &sep, &quit])?;
            let menu = Menu::with_items(&h, &[&sub])?;
            h.set_menu(menu)?;
            h.on_menu_event(|app, e| {
                let Some(w) = app.get_webview_window("main") else { return };
                match e.id().as_ref() {
                    "reload" => { let _ = w.eval("location.reload()"); }
                    "home" => {
                        match load_url(app).and_then(|u| Url::parse(&u).ok()) {
                            Some(u) => { let _ = w.navigate(u); }
                            None => { let _ = w.navigate(local_page()); }
                        }
                    }
                    "change" => { let _ = w.navigate(local_page()); }
                    _ => {}
                }
            });
            let start = match load_url(&h).and_then(|u| Url::parse(&u).ok()) {
                Some(u) => WebviewUrl::External(u),
                None => WebviewUrl::App("index.html".into()),
            };
            WebviewWindowBuilder::new(app, "main", start)
                .title("TriCloud")
                .inner_size(1280.0, 820.0)
                .min_inner_size(420.0, 520.0)
                .center()
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("TriCloud 启动失败");
}
