//! The user's own checkpoints (from Civitai, Hugging Face or anywhere else): import, list, assign to an architecture, delete.
//! The architecture comes from the file's folder (`<models>/<ckptKind>/<family id>/x.safetensors`), else its name (`match`),
//! else its safetensors header (`detect`: key fragments that must all occur) - so a file named "myMix_v3" still lands right.
use serde::Serialize;
use serde_json::Value;
use std::path::{Path, PathBuf};

use crate::config::Config;
use crate::plugins::Registry;

const KINDS: [&str; 2] = ["diffusion_models", "checkpoints"];
const EXTS: [&str; 3] = ["safetensors", "gguf", "ckpt"];

/// family_def of the switched-on model family plugins, in their match order
pub fn families(reg: &Registry, c: &Config) -> Vec<Value> {
    let mut out: Vec<Value> = reg.enabled(&c.plugins).into_iter().filter_map(|p| p.m.family_def.clone()).collect();
    out.sort_by(|a, b| a["order"].as_f64().unwrap_or(99.0).total_cmp(&b["order"].as_f64().unwrap_or(99.0)));
    out
}

/// family by folder ("anima38\x.safetensors") or by name (the first family whose `match` alternatives occur in it)
pub fn family_of(fams: &[Value], file: &str) -> Option<String> {
    let mut parts = file.split(['/', '\\']);
    let first = parts.next().unwrap_or(file);
    let n = file.rsplit(['/', '\\']).next().unwrap_or(file).to_lowercase();
    if n != first.to_lowercase() {
        if let Some(d) = fams.iter().find(|d| d["id"].as_str() == Some(first)) {
            return d["id"].as_str().map(String::from);
        }
    }
    // `match` = plain alternatives ("a|b|c"), compared case-insensitively like the regex in families.ts
    fams.iter().find(|d| d["match"].as_str().unwrap_or("").to_lowercase().split('|').any(|m| !m.is_empty() && n.contains(m)))
        .and_then(|d| d["id"].as_str().map(String::from))
}

/// tensor names of a .safetensors file (header only, a few hundred KB even for 20 GB files)
fn tensor_names(p: &Path) -> Option<Vec<String>> {
    use std::io::Read;
    let mut f = std::fs::File::open(p).ok()?;
    let mut len = [0u8; 8];
    f.read_exact(&mut len).ok()?;
    let n = u64::from_le_bytes(len);
    if n == 0 || n > 100 << 20 {
        return None;
    }
    let mut buf = vec![0u8; n as usize];
    f.read_exact(&mut buf).ok()?;
    let h: serde_json::Map<String, Value> = serde_json::from_slice(&buf).ok()?;
    Some(h.into_iter().map(|(k, _)| k).filter(|k| k != "__metadata__").collect())
}

/// architecture by the file's tensors: the first family (by order) whose `detect` fragments all occur in some tensor name
pub fn detect(fams: &[Value], p: &Path) -> Option<String> {
    let keys = tensor_names(p)?;
    fams.iter().find(|d| {
        let frags: Vec<&str> = d["detect"].as_array().into_iter().flatten().filter_map(|x| x.as_str()).collect();
        !frags.is_empty() && frags.iter().all(|fr| keys.iter().any(|k| k.contains(fr)))
    }).and_then(|d| d["id"].as_str().map(String::from))
}

#[derive(Serialize)]
pub struct Ckpt {
    kind: String,
    file: String,
    size: u64,
    /// architecture by folder / name ("" = the pickers offer it everywhere, marked)
    family: String,
    /// architecture by the header when folder and name say nothing - the UI offers to assign it
    detected: String,
}

fn walk(root: &Path, dir: &Path, out: &mut Vec<(String, u64)>) {
    for f in std::fs::read_dir(dir).into_iter().flatten().flatten() {
        let p = f.path();
        let link = f.file_type().map(|t| t.is_symlink()).unwrap_or(true);
        if p.is_dir() && !link {
            walk(root, &p, out);
        } else if p.extension().and_then(|x| x.to_str()).is_some_and(|x| EXTS.contains(&x)) {
            let rel = p.strip_prefix(root).unwrap().to_string_lossy().replace(['/', '\\'], std::path::MAIN_SEPARATOR_STR);
            out.push((rel, f.metadata().map(|m| m.len()).unwrap_or(0)));
        }
    }
}

pub fn list(reg: &Registry, c: &Config) -> Vec<Ckpt> {
    let Some(models) = c.models_dir() else { return vec![] };
    let fams = families(reg, c);
    let mut out = vec![];
    for kind in KINDS {
        let root = models.join(kind);
        let mut files = vec![];
        walk(&root, &root, &mut files);
        for (file, size) in files {
            let family = family_of(&fams, &file).unwrap_or_default();
            let detected = if family.is_empty() { detect(&fams, &root.join(&file)).unwrap_or_default() } else { String::new() };
            out.push(Ckpt { kind: kind.into(), file, size, family, detected });
        }
    }
    out.sort_by(|a, b| a.file.to_lowercase().cmp(&b.file.to_lowercase()));
    out
}

/// a relative model path from the UI: no absolute paths, no "..", no drive letters
fn safe_rel(kind: &str, file: &str) -> Result<(), String> {
    let bad = file.is_empty() || file.contains(':') || file.starts_with(['/', '\\'])
        || file.split(['/', '\\']).any(|s| s.is_empty() || s == "." || s == "..")
        || !Path::new(file).extension().and_then(|x| x.to_str()).is_some_and(|x| EXTS.contains(&x));
    if !KINDS.contains(&kind) || bad { Err("invalid model path".into()) } else { Ok(()) }
}

fn family_kind<'a>(fams: &'a [Value], id: &str) -> Result<&'a str, String> {
    let d = fams.iter().find(|d| d["id"].as_str() == Some(id)).ok_or(format!("unknown architecture {id}"))?;
    Ok(d["ckptKind"].as_str().unwrap_or("diffusion_models"))
}

/// hard link when source and engine share a drive (instant, no second copy of 10-20 GB), else copy via .part
fn place(src: &Path, dst: &Path) -> Result<(), String> {
    std::fs::create_dir_all(dst.parent().unwrap()).map_err(|e| e.to_string())?;
    if dst.exists() {
        if std::fs::canonicalize(src).ok() == std::fs::canonicalize(dst).ok() {
            return Ok(());
        }
        return Err(format!("{} already exists", dst.file_name().unwrap().to_string_lossy()));
    }
    if std::fs::hard_link(src, dst).is_ok() {
        return Ok(());
    }
    let mut tmp = dst.as_os_str().to_owned();
    tmp.push(".part");
    let tmp = PathBuf::from(tmp);
    let res = std::fs::copy(src, &tmp).and_then(|_| std::fs::rename(&tmp, dst));
    if res.is_err() {
        let _ = std::fs::remove_file(&tmp);   // no hidden multi-GB leftover
    }
    res.map_err(|e| e.to_string())
}

/// import a checkpoint for `family` (None = detect it); returns (family, path relative to its models folder)
pub fn import(reg: &Registry, c: &Config, path: &str, family: Option<String>) -> Result<(String, String), String> {
    let src = PathBuf::from(path);
    if !src.extension().and_then(|x| x.to_str()).is_some_and(|x| EXTS.contains(&x)) {
        return Err("only .safetensors / .gguf / .ckpt files".into());
    }
    if !src.is_file() {
        return Err(format!("{} not found", src.display()));
    }
    let fams = families(reg, c);
    let name = src.file_name().unwrap().to_string_lossy().to_string();
    let fam = match family.filter(|f| !f.is_empty()) {
        Some(f) => f,
        None => detect(&fams, &src).or_else(|| family_of(&fams, &name))
            .ok_or("architecture not recognised - choose it in the list")?,
    };
    let kind = family_kind(&fams, &fam)?;
    let models = c.models_dir().ok_or("no install folder")?;
    let dst = models.join(kind).join(&fam).join(&name);
    let inside = std::fs::canonicalize(&src).ok().zip(std::fs::canonicalize(&models).ok()).is_some_and(|(s, m)| s.starts_with(m));
    if inside && std::fs::canonicalize(&src).ok() != std::fs::canonicalize(&dst).ok() {
        if dst.exists() {
            return Err(format!("{name} already exists"));
        }
        std::fs::create_dir_all(dst.parent().unwrap()).map_err(|e| e.to_string())?;
        std::fs::rename(&src, &dst).map_err(|e| e.to_string())?;
    } else {
        place(&src, &dst)?;
    }
    let rel = format!("{fam}{}{name}", std::path::MAIN_SEPARATOR);
    Ok((fam, rel))
}

/// move a listed file into `<ckptKind of family>/<family>/` so folder, pickers and MCP agree on its architecture
pub fn assign(reg: &Registry, c: &Config, kind: &str, file: &str, family: &str) -> Result<String, String> {
    safe_rel(kind, file)?;
    let fams = families(reg, c);
    let to_kind = family_kind(&fams, family)?;
    let models = c.models_dir().ok_or("no install folder")?;
    let src = models.join(kind).join(file);
    if !src.is_file() {
        return Err("not a model file".into());
    }
    let name = src.file_name().ok_or("invalid model path")?.to_owned();
    let dst = models.join(to_kind).join(family).join(&name);
    if dst.exists() {
        return Err(format!("{} already exists", name.to_string_lossy()));
    }
    std::fs::create_dir_all(dst.parent().unwrap()).map_err(|e| e.to_string())?;
    std::fs::rename(&src, &dst).map_err(|e| e.to_string())?;
    Ok(format!("{family}{}{}", std::path::MAIN_SEPARATOR, name.to_string_lossy()))
}

pub fn delete(c: &Config, kind: &str, file: &str) -> Result<(), String> {
    safe_rel(kind, file)?;
    let p = c.models_dir().ok_or("no install folder")?.join(kind).join(file);
    if !p.is_file() {
        return Err("not a model file".into());
    }
    std::fs::remove_file(&p).map_err(|e| e.to_string())?;
    // an emptied family folder goes too (never the kind folder itself)
    if let Some(d) = p.parent().filter(|d| d.file_name().is_some_and(|n| n != kind)) {
        let _ = std::fs::remove_dir(d);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn fams() -> Vec<Value> {
        vec![
            json!({"id": "moss", "match": "moss|kromoss", "detect": ["rope.bands", "final_linear_video.weight"], "order": 1}),
            json!({"id": "anima38", "match": "anima-3.8b", "detect": ["anima_v2_connector."], "order": 2.5}),
            json!({"id": "anima", "match": "anima", "detect": ["blocks.0.adaln_modulation_cross_attn.", "llm_adapter."], "order": 3}),
        ]
    }

    fn st(dir: &Path, name: &str, keys: &[&str]) -> PathBuf {
        let h: serde_json::Map<String, Value> = keys.iter().map(|k| (k.to_string(), json!({"dtype": "F16", "shape": [1], "data_offsets": [0, 2]}))).collect();
        let hb = serde_json::to_vec(&h).unwrap();
        let mut b = (hb.len() as u64).to_le_bytes().to_vec();
        b.extend(hb);
        b.extend([0, 0]);
        let p = dir.join(name);
        std::fs::write(&p, b).unwrap();
        p
    }

    #[test]
    fn folder_name_and_header_decide_the_architecture() {
        let f = fams();
        assert_eq!(family_of(&f, "anima38\\myMix.safetensors").as_deref(), Some("anima38"));
        assert_eq!(family_of(&f, "anima-3.8b/animaExpanded38B_10.safetensors").as_deref(), Some("anima"));   // folder is no id
        assert_eq!(family_of(&f, "miaomiaoHaremMOSS_baseV10_fp16.safetensors").as_deref(), Some("moss"));
        assert_eq!(family_of(&f, "myMix_v3.safetensors"), None);
        let d = std::env::temp_dir().join(format!("fumika_ckpt_{}", std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        let m = st(&d, "a.safetensors", &["rope.bands", "final_linear_video.weight", "layers.0.k_norm.weight"]);
        let pro = st(&d, "b.safetensors", &["net.blocks.0.adaln_modulation_cross_attn.1.weight", "net.llm_adapter.x", "net.anima_v2_connector.q"]);
        let an = st(&d, "c.safetensors", &["net.blocks.0.adaln_modulation_cross_attn.1.weight", "net.llm_adapter.x"]);
        let other = st(&d, "d.safetensors", &["double_blocks.0.img_attn.qkv.weight"]);
        assert_eq!(detect(&f, &m).as_deref(), Some("moss"));
        assert_eq!(detect(&f, &pro).as_deref(), Some("anima38"));
        assert_eq!(detect(&f, &an).as_deref(), Some("anima"));
        assert_eq!(detect(&f, &other), None);
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn paths_from_the_ui_stay_inside_the_models_folder() {
        assert!(safe_rel("checkpoints", "sdxl\\x.safetensors").is_ok());
        for bad in ["", "..\\x.safetensors", "a/../../x", "C:\\x.safetensors", "\\x", "a//b.safetensors", "sdxl", "x.yaml"] {
            assert!(safe_rel("checkpoints", bad).is_err(), "{bad}");
        }
        assert!(safe_rel("loras", "x.safetensors").is_err());
    }
}

#[cfg(test)]
mod real_files {
    #[test]
    #[ignore]
    fn detect_real_checkpoints() {
        let mut fams = vec![];
        for p in ["family-moss", "family-sdxl", "family-anima", "family-anima38"] {
            let m: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(format!("resources/plugins/{p}/plugin.json")).unwrap()).unwrap();
            fams.push(m["family_def"].clone());
        }
        fams.sort_by(|a, b| a["order"].as_f64().unwrap().total_cmp(&b["order"].as_f64().unwrap()));
        for f in std::env::var("CKPTS").unwrap().split(';') {
            println!("{:>8}  {f}", super::detect(&fams, std::path::Path::new(f)).unwrap_or("-".into()));
        }
    }
}
