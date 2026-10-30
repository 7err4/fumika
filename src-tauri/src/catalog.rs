//! Model catalog: everything the app can download. The core brings only the engine (models.json); every other model comes from
//! a plugin manifest. A model several plugins share (MOSS base, text encoder) appears once and lists all its plugins.
use crate::plugins::{Plugin, Registry};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Item {
    pub id: String,
    pub name: String,
    pub file: String,
    /// sub-folder of ComfyUI/models ("diffusion_models", "text_encoders", "vae", "loras") or "" for the ComfyUI archive
    pub dest: String,
    pub url: String,
    pub size: u64,
    /// "required" | "recommended" | "optional"
    pub kind: String,
    /// alternative group: only one item per group is needed (bf16 vs int8 base model)
    #[serde(default)]
    pub group: String,
    #[serde(default)]
    pub note: String,
    /// licence of the weights - shown before a download
    #[serde(default)]
    pub license: String,
    #[serde(default)]
    pub license_url: String,
    /// non-commercial licence: the UI asks for an explicit OK before the plugin is switched on
    #[serde(default)]
    pub license_noncommercial: bool,
    /// plugins that need this model (filled in by the catalog, "" = the core)
    #[serde(default)]
    pub plugins: Vec<String>,
    /// "windows" | "linux" = only on that system (the engine downloads), "" = everywhere
    #[serde(default)]
    pub os: String,
}

const CORE: &str = include_str!("../models.json");

/// the engine item: the portable build on Windows, the ComfyUI source (+ uv for its Python) on Linux
pub const ENGINE: &str = if cfg!(windows) { "comfy_portable" } else { "comfy_linux" };

fn core() -> Vec<Item> {
    let all: Vec<Item> = serde_json::from_str(CORE).expect("models.json is valid");
    let mut items: Vec<Item> = all.into_iter().filter(|i| i.os.is_empty() || i.os == std::env::consts::OS).collect();
    if let Some(engine) = items.iter_mut().find(|i| i.id == "comfy_linux") {
        describe_linux_engine(engine, crate::system::use_rocm());
    }
    items
}

/// Use the installer's backend decision so the setup label cannot independently select a different backend.
fn describe_linux_engine(engine: &mut Item, rocm: bool) {
    let backend = if rocm { "AMD ROCm" } else { "NVIDIA CUDA" };
    engine.name = format!("ComfyUI 0.42 for Linux ({backend})");
    engine.note = format!("the image engine; Python 3.13 and PyTorch for {backend} are installed into its own folder - does not touch other installs");
}

fn merge<'a>(plugins: impl Iterator<Item = &'a Plugin>) -> Vec<Item> {
    let mut out = core();
    for p in plugins {
        for m in &p.m.models {
            match out.iter_mut().find(|i| i.id == m.id) {
                Some(i) => i.plugins.push(p.m.id.clone()),
                None => {
                    let mut m = m.clone();
                    m.plugins = vec![p.m.id.clone()];
                    out.push(m);
                }
            }
        }
    }
    out
}

/// what the user needs: the engine + the models of the plugins they switched on
pub fn items(reg: &Registry, enabled: &Option<Vec<String>>) -> Vec<Item> {
    merge(reg.enabled(enabled).into_iter())
}

/// any known model, also of plugins that are off (downloads started from a plugin card before switching it on)
pub fn get(reg: &Registry, id: &str) -> Option<Item> {
    merge(reg.0.iter()).into_iter().find(|i| i.id == id)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn linux_setup_describes_the_selected_backend_without_changing_downloads() {
        let all: Vec<Item> = serde_json::from_str(CORE).unwrap();
        let original = all.into_iter().find(|i| i.id == "comfy_linux").unwrap();
        for (rocm, backend) in [(true, "AMD ROCm"), (false, "NVIDIA CUDA")] {
            let mut engine = original.clone();
            describe_linux_engine(&mut engine, rocm);
            assert!(engine.name.contains(backend));
            assert!(engine.note.contains(backend));
            assert_eq!(engine.id, original.id);
            assert_eq!(engine.file, original.file);
            assert_eq!(engine.url, original.url);
            assert_eq!(engine.os, original.os);
        }
    }

    #[test]
    fn shared_models_are_listed_once() {
        let reg = crate::plugins::discover(std::path::Path::new("resources"));
        let all = Some(reg.0.iter().map(|p| p.m.id.clone()).collect());
        let it = items(&reg, &all);
        assert_eq!(it.iter().filter(|i| i.id == "qwen_te").count(), 1);
        let te = it.iter().find(|i| i.id == "qwen_te").unwrap();
        assert!(te.plugins.contains(&"moss-doujin".to_string()) && te.plugins.contains(&"moss-lora-trainer".to_string()));
        assert!(it.iter().any(|i| i.id == ENGINE));
        assert!(items(&reg, &None).iter().all(|i| i.plugins.is_empty() && i.os == std::env::consts::OS), "only this system's engine downloads");
        assert!(it.iter().filter(|i| i.id.starts_with("anima")).all(|i| i.license_noncommercial));
    }
}
