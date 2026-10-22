//! Comic projects on disk: a series (cast, style, model settings) with chapters (story, scenes, pages), one folder per series
//! in the app's config folder: projects/<series id>/series.json + chapters/<chapter id>.json. The web view owns the content
//! (plain JSON); this module only stores it. Deleting moves the files to projects/_deleted/ so nothing is lost by a misclick.
use serde::Serialize;
use serde_json::Value;
use std::path::PathBuf;

pub fn root() -> PathBuf {
    crate::config::app_dir().join("projects")
}

/// ids are made by the web view ("s1a2b3", "c9f8"): letters, digits, - and _ only, so they never leave their folder
fn id_ok(id: &str) -> Result<(), String> {
    let ok = !id.is_empty() && id.len() <= 64 && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') && !id.starts_with('_');
    if ok { Ok(()) } else { Err(format!("invalid id {id:?}")) }
}

fn write_json(p: &std::path::Path, v: &Value) -> Result<(), String> {
    std::fs::create_dir_all(p.parent().unwrap()).map_err(|e| e.to_string())?;
    let tmp = p.with_extension("json.part");
    std::fs::write(&tmp, serde_json::to_vec_pretty(v).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, p).map_err(|e| e.to_string())
}

fn read_json(p: &std::path::Path) -> Result<Value, String> {
    serde_json::from_slice(&std::fs::read(p).map_err(|e| e.to_string())?).map_err(|e| e.to_string())
}

#[derive(Serialize)]
pub struct Listing {
    /// the projects folder exists (false = first start: the web view creates the example series / takes over the old project)
    exists: bool,
    /// series.json of every series (the web view keeps title, chapter list and order there), newest change first
    series: Vec<Value>,
}

pub fn list() -> Listing {
    let r = root();
    let mut series: Vec<(std::time::SystemTime, Value)> = std::fs::read_dir(&r).into_iter().flatten().flatten()
        .filter(|e| e.path().is_dir() && !e.file_name().to_string_lossy().starts_with('_'))
        .filter_map(|e| {
            let p = e.path().join("series.json");
            let t = std::fs::metadata(&p).and_then(|m| m.modified()).ok()?;
            Some((t, read_json(&p).ok()?))
        })
        .collect();
    series.sort_by(|a, b| b.0.cmp(&a.0));
    Listing { exists: r.is_dir(), series: series.into_iter().map(|(_, v)| v).collect() }
}

pub fn save_series(id: &str, data: &Value) -> Result<(), String> {
    id_ok(id)?;
    write_json(&root().join(id).join("series.json"), data)
}

pub fn load_chapter(series: &str, chapter: &str) -> Result<Value, String> {
    id_ok(series)?;
    id_ok(chapter)?;
    read_json(&root().join(series).join("chapters").join(format!("{chapter}.json")))
}

pub fn save_chapter(series: &str, chapter: &str, data: &Value) -> Result<(), String> {
    id_ok(series)?;
    id_ok(chapter)?;
    write_json(&root().join(series).join("chapters").join(format!("{chapter}.json")), data)
}

fn stamp() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

/// a whole series -> projects/_deleted/<id>-<time>
pub fn delete_series(id: &str) -> Result<(), String> {
    id_ok(id)?;
    let src = root().join(id);
    if !src.is_dir() {
        return Ok(());
    }
    let dst = root().join("_deleted").join(format!("{id}-{}", stamp()));
    std::fs::create_dir_all(dst.parent().unwrap()).map_err(|e| e.to_string())?;
    std::fs::rename(src, dst).map_err(|e| e.to_string())
}

/// one chapter file -> projects/_deleted/<series>-<chapter>-<time>.json (the web view removes it from series.json)
pub fn delete_chapter(series: &str, chapter: &str) -> Result<(), String> {
    id_ok(series)?;
    id_ok(chapter)?;
    let src = root().join(series).join("chapters").join(format!("{chapter}.json"));
    if !src.is_file() {
        return Ok(());
    }
    let dst = root().join("_deleted").join(format!("{series}-{chapter}-{}.json", stamp()));
    std::fs::create_dir_all(dst.parent().unwrap()).map_err(|e| e.to_string())?;
    std::fs::rename(src, dst).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    #[test]
    fn ids_stay_inside_the_projects_folder() {
        for ok in ["s1a2b3", "c-9_f8", "deadline"] {
            assert!(super::id_ok(ok).is_ok(), "{ok}");
        }
        for bad in ["", "..", "a/b", "a\\b", "C:x", "_deleted", "x.json", &"a".repeat(65)] {
            assert!(super::id_ok(bad).is_err(), "{bad}");
        }
    }
}
