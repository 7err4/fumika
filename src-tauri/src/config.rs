//! App settings in %APPDATA%/Fumika/config.json
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Config {
    /// folder that contains the engine (ComfyUI_windows_portable/ or ComfyUI_engine/) and the downloads/ cache
    pub install_dir: Option<PathBuf>,
    pub port: u16,
    /// catalog id of the base model to use ("moss_base_bf16" / "moss_base_int8" / "kromoss")
    pub base_model: String,
    /// local MCP server (http://127.0.0.1:<mcp_port>/mcp, Bearer <mcp_token>) for LM Studio / Claude / other agents
    #[serde(default)]
    pub mcp_enabled: bool,
    #[serde(default = "default_mcp_port")]
    pub mcp_port: u16,
    #[serde(default)]
    pub mcp_token: String,
    /// ids of the plugins the user switched on; None = not chosen yet (first start shows the plugin choice)
    #[serde(default)]
    pub plugins: Option<Vec<String>>,
    /// what the window's X does: "" = ask (first close explains the tray), "tray" = hide to the tray, "quit" = end the app
    #[serde(default)]
    pub close_action: String,
    /// exports (picture export, CBZ) without the prompt data: ComfyUI's graph and the A1111 parameters (the AI marking stays)
    #[serde(default)]
    pub export_strip_prompt: bool,
}

fn default_mcp_port() -> u16 {
    8292
}

impl Default for Config {
    fn default() -> Self {
        Self { install_dir: None, port: 8291, base_model: "moss_base_bf16".into(), mcp_enabled: false, mcp_port: default_mcp_port(), mcp_token: String::new(), plugins: None, close_action: String::new(), export_strip_prompt: false }
    }
}

/// %APPDATA%/Fumika (config.json, studio.db). The app was called MOSS Doujin Studio (and briefly Sumi Studio) until 21 Oct
/// 2026: an old folder is moved over once, so settings and the render queue survive the rename.
pub fn app_dir() -> PathBuf {
    let base = dirs::config_dir().unwrap_or_else(|| PathBuf::from("."));
    let dir = base.join("Fumika");
    for old in ["Sumi Studio", "MOSS Doujin Studio"] {
        if !dir.exists() && base.join(old).exists() {
            let _ = std::fs::rename(base.join(old), &dir);
        }
    }
    dir
}

fn path() -> PathBuf {
    app_dir().join("config.json")
}

pub fn load() -> Config {
    std::fs::read_to_string(path()).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default()
}

pub fn save(c: &Config) -> anyhow::Result<()> {
    let p = path();
    std::fs::create_dir_all(p.parent().unwrap())?;
    std::fs::write(p, serde_json::to_string_pretty(c)?)?;
    Ok(())
}

impl Config {
    /// the engine folder: the portable build's own name on Windows, ComfyUI_engine (ComfyUI/, venv/, python/, bin/) on Linux
    pub fn comfy_dir(&self) -> Option<PathBuf> {
        self.install_dir.as_ref().map(|d| d.join(if cfg!(windows) { "ComfyUI_windows_portable" } else { "ComfyUI_engine" }))
    }
    pub fn models_dir(&self) -> Option<PathBuf> {
        self.comfy_dir().map(|d| d.join("ComfyUI").join("models"))
    }
    pub fn downloads_dir(&self) -> Option<PathBuf> {
        self.install_dir.as_ref().map(|d| d.join("downloads"))
    }
}
