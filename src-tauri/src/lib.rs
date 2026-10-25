//! Fumika - Tauri commands. The web UI calls these for setup / models / server and reaches the ComfyUI API only
//! through `comfy_request` and the `comfyimg` URI scheme (ComfyUI keeps its origin check, no CORS opened).
mod aimark;
mod catalog;
mod cbz;
mod checkpoints;
mod comfy;
mod config;
mod download;
mod graphs;
mod genparams;
mod gpulock;
mod mcp;
mod plugins;
mod projects;
mod queue;
mod shell;
mod system;
mod trainer;

use serde::Serialize;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};

pub(crate) struct AppState {
    pub(crate) cfg: Mutex<config::Config>,
    dl: download::Downloads,
    srv: comfy::Server,
}

type R<T> = Result<T, String>;
fn e<E: std::fmt::Display>(x: E) -> String {
    x.to_string()
}

#[derive(Serialize)]
struct ItemStatus {
    #[serde(flatten)]
    item: catalog::Item,
    installed: bool,
    partial_bytes: u64,
    path: Option<String>,
}

pub(crate) fn target_of(c: &config::Config, it: &catalog::Item) -> Option<PathBuf> {
    if it.dest.is_empty() {
        c.downloads_dir().map(|d| d.join(&it.file))
    } else {
        c.models_dir().map(|d| d.join(&it.dest).join(&it.file))
    }
}

#[tauri::command]
fn get_config(st: State<AppState>) -> config::Config {
    st.cfg.lock().unwrap().clone()
}

#[tauri::command]
fn set_config(st: State<AppState>, mut new: config::Config) -> R<()> {
    // the plugin choice is owned by plugins_set (it adds required families); a settings save never changes it
    new.plugins = st.cfg.lock().unwrap().plugins.clone();
    new.close_action = st.cfg.lock().unwrap().close_action.clone();   // set only by close_choice
    config::save(&new).map_err(e)?;
    *st.cfg.lock().unwrap() = new;
    Ok(())
}

/// VRAM used / total in MB (null without an NVIDIA GPU)
#[tauri::command]
async fn gpu_usage() -> Option<(u64, u64)> {
    tokio::task::spawn_blocking(system::vram).await.ok().flatten()
}

#[tauri::command]
fn system_check(dir: String) -> system::Report {
    system::report(&PathBuf::from(dir))
}

#[tauri::command]
fn catalog_status(st: State<AppState>, reg: State<plugins::Registry>) -> Vec<ItemStatus> {
    let c = st.cfg.lock().unwrap().clone();
    catalog::items(&reg, &c.plugins)
        .into_iter()
        .map(|it| {
            let t = target_of(&c, &it);
            let installed = if it.id == catalog::ENGINE { comfy::is_installed(&c) } else { t.as_ref().map(|p| p.exists()).unwrap_or(false) };
            let partial_bytes = t
                .as_ref()
                .and_then(|p| std::fs::metadata(p.with_extension(format!("{}.part", p.extension().and_then(|x| x.to_str()).unwrap_or("bin")))).ok())
                .map(|m| m.len())
                .unwrap_or(0);
            ItemStatus { path: t.map(|p| p.display().to_string()), item: it, installed, partial_bytes }
        })
        .collect()
}

#[tauri::command]
async fn download(app: AppHandle, st: State<'_, AppState>, reg: State<'_, plugins::Registry>, id: String) -> R<()> {
    let c = st.cfg.lock().unwrap().clone();
    let it = catalog::get(&reg, &id).ok_or("unknown model id")?;
    let target = target_of(&c, &it).ok_or("choose an install folder first")?;
    if it.url.is_empty() {
        return Err(format!("{} has no download yet - add the file with \"Choose file\"", it.name));
    }
    // already complete (e.g. the engine archive before "Install engine" extracted it): no second download
    if std::fs::metadata(&target).map(|m| it.size == 0 || m.len() == it.size).unwrap_or(false) {
        download::done(&app, &id, it.size);
        return Ok(());
    }
    download::fetch(app, st.dl.clone(), id, it.url.clone(), target, it.size).await.map_err(e)
}

#[tauri::command]
fn cancel_download(st: State<AppState>, id: String) {
    st.dl.cancel(&id);
}

#[tauri::command]
fn delete_model(st: State<AppState>, reg: State<plugins::Registry>, id: String) -> R<()> {
    let c = st.cfg.lock().unwrap().clone();
    let it = catalog::get(&reg, &id).ok_or("unknown model id")?;
    if it.id == catalog::ENGINE {
        return Err("ComfyUI itself cannot be deleted here".into());
    }
    let t = target_of(&c, &it).ok_or("no install folder")?;
    if t.exists() {
        std::fs::remove_file(&t).map_err(e)?;
    }
    Ok(())
}

/// A model without a public download (local test files such as the CharRef LoRA): copy the user's file to its catalog place.
#[tauri::command]
fn import_model(st: State<AppState>, reg: State<plugins::Registry>, id: String, path: String) -> R<()> {
    let c = st.cfg.lock().unwrap().clone();
    let it = catalog::get(&reg, &id).ok_or("unknown model id")?;
    let src = PathBuf::from(&path);
    if src.extension() != std::path::Path::new(&it.file).extension() {
        return Err(format!("expected a {} file", it.file));
    }
    let dst = target_of(&c, &it).ok_or("no install folder")?;
    std::fs::create_dir_all(dst.parent().unwrap()).map_err(e)?;
    // also replaces an installed file (e.g. a newer CharRef); the same file picked again is a no-op (copy onto itself truncates)
    if dst.exists() && std::fs::canonicalize(&src).ok() == std::fs::canonicalize(&dst).ok() {
        return Ok(());
    }
    let tmp = dst.with_extension("part");
    std::fs::copy(&src, &tmp).map_err(e)?;
    std::fs::rename(&tmp, &dst).map_err(e)?;
    Ok(())
}

/// The book's reference picture (CharRef) -> ComfyUI/input/fumika_refs; returns the LoadImage name.
#[tauri::command]
fn import_reference(st: State<AppState>, path: String) -> R<String> {
    let c = st.cfg.lock().unwrap().clone();
    comfy::import_reference(&c, &PathBuf::from(path)).map_err(e)
}

#[derive(serde::Deserialize)]
struct OutFile {
    filename: String,
    #[serde(default)]
    subfolder: String,
}

/// Export rendered images (Asset Studio sheets / sprites) from ComfyUI/output into a folder the user picked; returns the count.
#[tauri::command]
fn export_outputs(st: State<AppState>, files: Vec<OutFile>, dir: String) -> R<usize> {
    let c = st.cfg.lock().unwrap().clone();
    let dst = PathBuf::from(dir);
    std::fs::create_dir_all(&dst).map_err(e)?;
    for f in &files {
        let src = comfy::output_file(&c, &f.subfolder, &f.filename).map_err(e)?;
        aimark::export_copy(&src, &dst.join(&f.filename), c.export_strip_prompt).map_err(e)?;
    }
    Ok(files.len())
}

/// GPU lock state: is a training holding back the render queue, and did the user override it?
#[tauri::command]
fn queue_gate(lock: State<gpulock::GpuLock>) -> gpulock::Gate {
    lock.gate()
}

/// "render anyway" while a training runs (ends with the training)
#[tauri::command]
fn queue_override(app: AppHandle, lock: State<gpulock::GpuLock>, on: bool) -> gpulock::Gate {
    lock.set_override(on);
    let g = lock.gate();
    let _ = app.emit("queue-gate", g.clone());
    g
}

/// Copy a user's own LoRA (.safetensors) into ComfyUI/models/loras.
#[tauri::command]
fn import_lora(st: State<AppState>, path: String) -> R<String> {
    let c = st.cfg.lock().unwrap().clone();
    let src = PathBuf::from(&path);
    if src.extension().and_then(|x| x.to_str()) != Some("safetensors") {
        return Err("only .safetensors files".into());
    }
    if !src.is_file() {
        return Err(format!("{} not found", src.display()));
    }
    let dst = c.models_dir().ok_or("no install folder")?.join("loras").join(src.file_name().unwrap());
    std::fs::create_dir_all(dst.parent().unwrap()).map_err(e)?;
    // a file already in models/loras picked again: copying it onto itself would truncate it
    if std::fs::canonicalize(&src).ok() != std::fs::canonicalize(&dst).ok() {
        std::fs::copy(&src, &dst).map_err(e)?;
    }
    Ok(dst.file_name().unwrap().to_string_lossy().to_string())
}

/// List the user's LoRAs (everything in models/loras except the turbo LoRA), with sizes.
#[tauri::command]
fn list_loras(st: State<AppState>) -> Vec<(String, u64)> {
    let c = st.cfg.lock().unwrap().clone();
    let Some(d) = c.models_dir().map(|m| m.join("loras")) else { return vec![] };
    let mut out = vec![];
    if let Ok(rd) = std::fs::read_dir(d) {
        for f in rd.flatten() {
            let n = f.file_name().to_string_lossy().to_string();
            if n.ends_with(".safetensors") && !n.contains("8steps") {
                out.push((n, f.metadata().map(|m| m.len()).unwrap_or(0)));
            }
        }
    }
    out
}

/// Model files of one models/ folder ("diffusion_models", "loras", ...), sub-folders included, named the way ComfyUI lists them
/// ("anima-2.9b\x.safetensors" on Windows) - for the checkpoint / LoRA pickers per architecture.
#[tauri::command]
fn list_models(st: State<AppState>, kind: String) -> R<Vec<(String, u64)>> {
    const KINDS: [&str; 6] = ["diffusion_models", "checkpoints", "loras", "text_encoders", "vae", "upscale_models"];
    if !KINDS.contains(&kind.as_str()) {
        return Err(format!("unknown model folder {kind}"));
    }
    let c = st.cfg.lock().unwrap().clone();
    let Some(root) = c.models_dir().map(|m| m.join(&kind)) else { return Ok(vec![]) };
    Ok(model_files(&root))
}

/// The inpaint mask painted in the Image Studio (PNG, white = redraw) -> ComfyUI/input/fumika_masks/<id>.png; returns the name
/// the workflow loads ("fumika_masks/<id>.png").
#[tauri::command]
fn save_mask(st: State<AppState>, png: Vec<u8>) -> R<String> {
    if !png.starts_with(b"\x89PNG\r\n\x1a\n") || png.len() > 64 << 20 {
        return Err("the mask must be a PNG of at most 64 MB".into());
    }
    let c = st.cfg.lock().unwrap().clone();
    let dir = c.comfy_dir().ok_or("no install folder")?.join("ComfyUI").join("input").join("fumika_masks");
    std::fs::create_dir_all(&dir).map_err(e)?;
    let name = format!("{}.png", uuid::Uuid::new_v4());
    std::fs::write(dir.join(&name), png).map_err(e)?;
    Ok(format!("fumika_masks/{name}"))
}

fn model_files(root: &std::path::Path) -> Vec<(String, u64)> {
    let mut out = vec![];
    let mut stack = vec![root.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else { continue };
        for f in rd.flatten() {
            let p = f.path();
            if p.is_dir() {
                stack.push(p);
            } else if matches!(p.extension().and_then(|x| x.to_str()), Some("safetensors" | "gguf" | "pt" | "pth" | "ckpt")) {
                let rel = p.strip_prefix(root).unwrap().to_string_lossy().replace(['/', '\\'], std::path::MAIN_SEPARATOR_STR);
                out.push((rel, f.metadata().map(|m| m.len()).unwrap_or(0)));
            }
        }
    }
    out.sort();
    out
}

/// The user's checkpoints of both model folders, with their architecture (folder / name, else the header's guess).
#[tauri::command]
async fn list_checkpoints(app: AppHandle) -> R<Vec<checkpoints::Ckpt>> {
    let c = app.state::<AppState>().cfg.lock().unwrap().clone();
    tokio::task::spawn_blocking(move || checkpoints::list(&app.state::<plugins::Registry>(), &c)).await.map_err(e)
}

/// Add a checkpoint file for an architecture (None = recognise it from the file) -> <ckptKind>/<family>/<file>.
/// Async + blocking thread: a 20 GB copy must not freeze the window.
#[tauri::command]
async fn import_checkpoint(app: AppHandle, path: String, family: Option<String>) -> R<(String, String)> {
    let c = app.state::<AppState>().cfg.lock().unwrap().clone();
    tokio::task::spawn_blocking(move || checkpoints::import(&app.state::<plugins::Registry>(), &c, &path, family)).await.map_err(e)?
}

#[tauri::command]
async fn assign_checkpoint(app: AppHandle, kind: String, file: String, family: String) -> R<String> {
    let c = app.state::<AppState>().cfg.lock().unwrap().clone();
    tokio::task::spawn_blocking(move || checkpoints::assign(&app.state::<plugins::Registry>(), &c, &kind, &file, &family)).await.map_err(e)?
}

#[tauri::command]
fn delete_checkpoint(st: State<AppState>, kind: String, file: String) -> R<()> {
    let c = st.cfg.lock().unwrap().clone();
    checkpoints::delete(&c, &kind, &file)
}

#[tauri::command]
fn delete_lora(st: State<AppState>, name: String) -> R<()> {
    let c = st.cfg.lock().unwrap().clone();
    if name.is_empty() || name.contains("..") || name.contains(['/', '\\', ':']) {
        return Err("invalid name".into());
    }
    std::fs::remove_file(c.models_dir().ok_or("no install folder")?.join("loras").join(name)).map_err(e)
}

/// CBZ of a chapter (page URLs in reading order, the cover first) at a path the user picked; returns the page count.
#[tauri::command]
async fn export_cbz(st: State<'_, AppState>, dest: String, pages: Vec<String>, comic_info: String) -> R<usize> {
    let c = st.cfg.lock().unwrap().clone();
    tokio::task::spawn_blocking(move || cbz::export(&c, &dest, &pages, &comic_info)).await.map_err(e)?.map_err(e)
}

/// Comic projects (series with chapters) on disk, see projects.rs.
#[tauri::command]
fn projects_list() -> projects::Listing {
    projects::list()
}

#[tauri::command]
fn series_save(id: String, data: serde_json::Value) -> R<()> {
    projects::save_series(&id, &data)
}

#[tauri::command]
fn series_delete(id: String) -> R<()> {
    projects::delete_series(&id)
}

#[tauri::command]
fn chapter_load(series: String, chapter: String) -> R<serde_json::Value> {
    projects::load_chapter(&series, &chapter)
}

#[tauri::command]
fn chapter_save(series: String, chapter: String, data: serde_json::Value) -> R<()> {
    projects::save_chapter(&series, &chapter, &data)
}

#[tauri::command]
fn chapter_delete(series: String, chapter: String) -> R<()> {
    projects::delete_chapter(&series, &chapter)
}

/// The answer to the first-close question: "tray" hides the window, "quit" ends the app; remember = do not ask again.
#[tauri::command]
fn close_choice(app: AppHandle, st: State<AppState>, choice: String, remember: bool) -> R<()> {
    if remember && (choice == "tray" || choice == "quit") {
        let mut c = st.cfg.lock().unwrap();
        c.close_action = choice.clone();
        config::save(&c).map_err(e)?;
    }
    match choice.as_str() {
        "quit" => app.exit(0),
        _ => if let Some(w) = app.get_webview_window("main") { let _ = w.hide(); },
    }
    Ok(())
}

/// Extract ComfyUI (after its download) and install the node packs of the plugins that are switched on.
#[tauri::command]
async fn install_comfy(app: AppHandle, st: State<'_, AppState>) -> R<Vec<String>> {
    let _busy = INSTALL.lock().await;
    let c = st.cfg.lock().unwrap().clone();
    if !comfy::is_installed(&c) {
        let file = |id: &str| -> R<PathBuf> {
            let it = catalog::get(&app.state::<plugins::Registry>(), id).unwrap();
            let p = target_of(&c, &it).ok_or("no install folder")?;
            if p.exists() { Ok(p) } else { Err(format!("{} is not downloaded yet", it.name)) }
        };
        let archive = file(catalog::ENGINE)?;
        #[cfg(windows)]
        {
            let dir = c.install_dir.clone().unwrap();
            tokio::task::spawn_blocking(move || comfy::extract(&archive, &dir)).await.map_err(e)?.map_err(e)?;
        }
        #[cfg(unix)]
        {
            // Python + PyTorch come from the internet during this step (about 4 GB, minutes): the UI shows a note meanwhile
            let uv = file("uv_linux")?;
            let c2 = c.clone();
            let _ = app.emit("engine-note", "python:ComfyUI");
            let r = tokio::task::spawn_blocking(move || comfy::install_linux(&c2, &archive, &uv)).await.map_err(e)?;
            let _ = app.emit("engine-note", "");
            r.map_err(e)?;
        }
    }
    install_plugin_nodes_bg(app, c).await
}

/// one engine install / node pack copy / pip run at a time (install_comfy, plugins_set and server_start can overlap)
static INSTALL: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

/// install_plugin_nodes off the async runtime: pip can take minutes
async fn install_plugin_nodes_bg(app: AppHandle, c: config::Config) -> R<Vec<String>> {
    tokio::task::spawn_blocking(move || install_plugin_nodes(&app, &c)).await.map_err(e)?
}

fn install_plugin_nodes(app: &AppHandle, c: &config::Config) -> R<Vec<String>> {
    let reg = app.state::<plugins::Registry>();
    let mut done = vec![];
    for p in reg.enabled(&c.plugins) {
        for d in p.node_dirs() {
            done.extend(comfy::install_node_pack(c, &d).map_err(e)?);
        }
        // Python packages the plugin's nodes need (once per requirement list); the UI shows a note meanwhile
        if !comfy::python_done(c, &p.m.id, &p.m.python) {
            let _ = app.emit("engine-note", format!("python:{}", p.m.name));
            let r = comfy::install_python(c, &p.m.id, &p.m.python);
            let _ = app.emit("engine-note", "");
            r.map_err(e)?;
            done.push(format!("python:{}", p.m.id));
        }
    }
    Ok(done)
}

/// One plugin card for Setup: the manifest, whether it is on, and how much it downloads.
#[derive(Serialize)]
struct PluginInfo<'a> {
    #[serde(flatten)]
    plugin: &'a plugins::Plugin,
    enabled: bool,
    download_bytes: u64,
    noncommercial_models: Vec<String>,
}

#[tauri::command]
fn plugins_list(st: State<AppState>, reg: State<plugins::Registry>) -> serde_json::Value {
    let c = st.cfg.lock().unwrap().clone();
    let on = c.plugins.clone().unwrap_or_default();
    let list: Vec<PluginInfo> = reg.0.iter().map(|p| {
        // alternatives (bf16 / int8) count once: the largest of a group; optional models are not counted
        let mut groups: std::collections::BTreeMap<String, u64> = Default::default();
        for m in p.m.models.iter().filter(|m| m.kind != "optional") {
            let k = if m.group.is_empty() { m.id.clone() } else { m.group.clone() };
            let v = groups.entry(k).or_default();
            *v = (*v).max(m.size);
        }
        PluginInfo { plugin: p, enabled: on.contains(&p.m.id), download_bytes: groups.values().sum(),
            noncommercial_models: p.m.models.iter().filter(|m| m.license_noncommercial).map(|m| m.name.clone()).collect() }
    }).collect();
    serde_json::json!({"chosen": c.plugins.is_some(), "plugins": list})
}

/// Switch plugins on / off (the choice at first start or in Setup). Installs the node packs when ComfyUI is there.
#[tauri::command]
async fn plugins_set(app: AppHandle, st: State<'_, AppState>, ids: Vec<String>) -> R<Vec<String>> {
    let mut c = st.cfg.lock().unwrap().clone();
    let reg = app.state::<plugins::Registry>();
    if let Some(bad) = ids.iter().find(|i| reg.get(i).is_none()) {
        return Err(format!("unknown plugin {bad}"));
    }
    // a workspace brings its model family (requires / requires_one in the manifests)
    c.plugins = Some(reg.with_requirements(&ids));
    config::save(&c).map_err(e)?;
    *st.cfg.lock().unwrap() = c.clone();
    if comfy::is_installed(&c) {
        let _busy = INSTALL.lock().await;
        install_plugin_nodes_bg(app, c).await
    } else {
        Ok(vec![])
    }
}

#[derive(Serialize)]
struct ServerStatus {
    installed: bool,
    running: bool,
    port: u16,
    log_tail: String,
    /// installed ComfyUI version ("0.42.1"); the UI asks to update below 0.42
    version: Option<String>,
    version_ok: bool,
    /// the engine serves the ComfyUI web page (the rail links it then; headless = API only, no link)
    ui: bool,
}

#[tauri::command]
async fn server_start(app: AppHandle, st: State<'_, AppState>) -> R<()> {
    // never start an engine while its install (or a node pack / pip update) is still running: half a venv, no torch
    let _busy = INSTALL.try_lock().map_err(|_| "the engine is still being installed or updated - start it when that is finished".to_string())?;
    let c = st.cfg.lock().unwrap().clone();
    // an engine left over from a crashed app still answers on the port: use it (a second one could not bind the port anyway;
    // the queue picks up its jobs - end-to-end test 22 Oct)
    if !comfy::running(&st.srv) && comfy::healthy(c.port).await {
        return if comfy::adopt(&c, &st.srv) { Ok(()) } else {
            Err(format!("port {} is used by another program (not Fumika's engine) - close it or pick another port in Setup", c.port))
        };
    }
    // an app update brings newer node packs (e.g. moss-doujin 1.4): copy the enabled plugins' packs before the engine loads them
    if comfy::is_installed(&c) && !comfy::running(&st.srv) {
        install_plugin_nodes_bg(app, c.clone()).await?;
    }
    comfy::start(&c, &st.srv).map_err(e)
}

#[tauri::command]
fn server_stop(st: State<AppState>) {
    comfy::stop(&st.srv);
}

#[tauri::command]
async fn server_status(st: State<'_, AppState>) -> R<ServerStatus> {
    let c = st.cfg.lock().unwrap().clone();
    let running = comfy::healthy(c.port).await;
    let log_tail = comfy::log_path(&c)
        .and_then(|p| std::fs::read_to_string(p).ok())
        .map(|s| s.lines().rev().take(12).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join("\n"))
        .unwrap_or_default();
    let version = comfy::version(&c);
    let version_ok = version.as_deref().map(comfy::at_least_0_42).unwrap_or(true);
    let ui = running && comfy::has_ui(c.port).await;
    Ok(ServerStatus { installed: comfy::is_installed(&c), running, port: c.port, log_tail, version, version_ok, ui })
}

/// The UI's only way to the ComfyUI API (see comfy::start for why there is no direct browser access).
#[tauri::command]
async fn comfy_request(st: State<'_, AppState>, method: String, path: String, body: Option<serde_json::Value>) -> R<serde_json::Value> {
    let port = st.cfg.lock().unwrap().port;
    comfy::request(port, &method, &path, body).await.map_err(e)
}

pub(crate) fn backend<R: tauri::Runtime>(app: &AppHandle<R>) -> queue::Backend {
    queue::Backend::Local { port: app.state::<AppState>().cfg.lock().unwrap().port }
}

/// Add one render job (a ComfyUI API graph) to the persistent queue; returns the job id.
#[tauri::command]
fn queue_add(q: State<queue::Queue>, project: String, label: String, graph: serde_json::Value, priority: Option<i64>) -> R<String> {
    q.add(&project, &label, &graph, priority.unwrap_or(0)).map_err(e)
}

/// Queue one workflow of a plugin (template + variables, rendered in plugins.rs, shared with the MCP server); returns the job id.
#[tauri::command]
fn queue_workflow(q: State<queue::Queue>, st: State<AppState>, reg: State<plugins::Registry>, project: String, label: String,
                  plugin: String, workflow: String, vars: serde_json::Value, priority: Option<i64>) -> R<String> {
    let on = st.cfg.lock().unwrap().plugins.clone().unwrap_or_default();
    if !on.contains(&plugin) {
        return Err(format!("plugin {plugin} is switched off"));
    }
    let g = reg.get(&plugin).ok_or("unknown plugin")?.render(&workflow, &vars).map_err(e)?;
    q.add(&project, &label, &g, priority.unwrap_or(0)).map_err(e)
}

#[tauri::command]
fn queue_list(q: State<queue::Queue>, project: Option<String>) -> R<Vec<queue::Job>> {
    q.list(project.as_deref()).map_err(e)
}

#[tauri::command]
async fn queue_cancel(app: AppHandle, id: String) -> R<()> {
    let running = app.state::<queue::Queue>().cancel(&id).map_err(e)?;
    if running {
        queue::interrupt(&backend(&app), &id).await;
    }
    Ok(())
}

/// training runs of the switched-on trainer plugins (models/loras/<family>_training/<name>)
#[tauri::command]
fn trainer_runs(st: State<AppState>) -> Vec<trainer::Run> {
    let c = st.cfg.lock().unwrap().clone();
    trainer::runs(&c, &c.plugins.clone().unwrap_or_default())
}

/// where a trainer plugin writes its runs (the Anima wizard needs an explicit output folder)
#[tauri::command]
fn trainer_dir(st: State<AppState>, plugin: String) -> R<String> {
    let c = st.cfg.lock().unwrap().clone();
    let sub = trainer::FOLDERS.iter().find(|(p, _)| *p == plugin).map(|(_, s)| *s).ok_or("not a trainer plugin")?;
    Ok(trainer::root(&c).ok_or("set up the engine first")?.join(sub).display().to_string())
}

#[tauri::command]
fn queue_retry(q: State<queue::Queue>, id: String) -> R<()> {
    q.requeue(&id).map_err(e)
}

/// MCP connection details for LM Studio / Claude (mcp.json snippet). Enabling takes effect after an app restart.
#[tauri::command]
fn mcp_info(st: State<AppState>) -> serde_json::Value {
    let c = st.cfg.lock().unwrap();
    let url = format!("http://127.0.0.1:{}/mcp", c.mcp_port);
    serde_json::json!({"enabled": c.mcp_enabled, "url": url, "token": c.mcp_token,
        "mcp_json": {"mcpServers": {"fumika": {"url": url, "headers": {"Authorization": format!("Bearer {}", c.mcp_token)}}}}})
}

/// %XX-decode a query value (paths from encodeURIComponent)
pub(crate) fn pct_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let Some(v) = std::str::from_utf8(&b[i + 1..i + 3]).ok().and_then(|h| u8::from_str_radix(h, 16).ok()) {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(if b[i] == b'+' { b' ' } else { b[i] });
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // AppImage: its AppRun sets PYTHONHOME / PYTHONPATH to the image's own usr/, every Python we start (uv, the engine venv)
    // then looks for its stdlib there and dies with "No module named 'encodings'" (GitHub issue #1, 24 Oct). A user's own
    // PYTHONHOME would break the .deb / Windows engine the same way. Fumika itself needs neither, so they go before any thread
    // or child process exists
    unsafe {
        std::env::remove_var("PYTHONHOME");
        std::env::remove_var("PYTHONPATH");
    }
    tauri::Builder::default()
        // first plugin: a second start (start menu while Fumika sits in the tray) only brings the running window back
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| shell::show_main(app)))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .register_asynchronous_uri_scheme_protocol("comfyimg", |ctx, req, responder| {
            let port = ctx.app_handle().state::<AppState>().cfg.lock().unwrap().port;
            let query = req.uri().query().unwrap_or("").to_string();
            tauri::async_runtime::spawn(async move {
                let res = match comfy::view(port, &query).await {
                    Ok((ct, bytes)) => tauri::http::Response::builder().header("Content-Type", ct).body(bytes),
                    Err(err) => tauri::http::Response::builder().status(502).body(err.to_string().into_bytes()),
                };
                responder.respond(res.unwrap());
            });
        })
        // sample images of training runs (only files below models/loras/*_training)
        .register_uri_scheme_protocol("trainimg", |ctx, req| {
            let c = ctx.app_handle().state::<AppState>().cfg.lock().unwrap().clone();
            let q = req.uri().query().unwrap_or("");
            let rel = q.split('&').find_map(|kv| kv.strip_prefix("path=")).map(pct_decode).unwrap_or_default();
            match trainer::sample(&c, &rel) {
                Ok((ct, bytes)) => tauri::http::Response::builder().header("Content-Type", ct).body(bytes).unwrap(),
                Err(err) => tauri::http::Response::builder().status(404).body(err.to_string().into_bytes()).unwrap(),
            }
        })
        .manage(AppState { cfg: Mutex::new(config::load()), dl: download::Downloads::default(), srv: comfy::Server::default() })
        .setup(|app| {
            app.manage(plugins::discover(&app.path().resource_dir()?));
            app.manage(queue::Queue::open(&config::app_dir().join("studio.db"))?);
            app.manage(gpulock::GpuLock::default());
            shell::setup(app)?;
            queue::spawn_dispatcher(app.handle().clone(), backend);
            queue::spawn_progress(app.handle().clone(), |a| a.state::<AppState>().cfg.lock().unwrap().port);
            let mut c = app.state::<AppState>().cfg.lock().unwrap().clone();
            if c.mcp_token.is_empty() {
                c.mcp_token = uuid::Uuid::new_v4().simple().to_string();
                let _ = config::save(&c);
                *app.state::<AppState>().cfg.lock().unwrap() = c.clone();
            }
            if c.mcp_enabled {
                mcp::spawn(app.handle().clone(), c.mcp_port, c.mcp_token.clone());
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_config, set_config, system_check, catalog_status, download, cancel_download, delete_model, import_lora,
            list_loras, list_models, save_mask, delete_lora, list_checkpoints, import_checkpoint, assign_checkpoint, delete_checkpoint, import_model, import_reference, install_comfy, server_start, server_stop, server_status, comfy_request,
            queue_add, queue_workflow, queue_list, plugins_list, plugins_set, queue_cancel, queue_retry, mcp_info, gpu_usage,
            trainer_runs, trainer_dir, export_outputs, queue_gate, queue_override, shell::app_ready, shell::tray_labels, close_choice, export_cbz, projects_list, series_save, series_delete, chapter_load, chapter_save, chapter_delete
        ])
        .on_window_event(|w, ev| match (ev, w.label()) {
            // X sends the window to the tray: the queue keeps rendering, "Quit" in the tray menu ends the app
            // the first time, the web view asks first (close_choice) so the user learns where Fumika went
            (tauri::WindowEvent::CloseRequested { api, .. }, "main") => {
                api.prevent_close();
                let action = w.state::<AppState>().cfg.lock().unwrap().close_action.clone();
                match action.as_str() {
                    "tray" => { let _ = w.hide(); }
                    "quit" => w.app_handle().exit(0),
                    _ => { let _ = w.emit("close-asked", ()); }
                }
            }
            (tauri::WindowEvent::Destroyed, "main") => comfy::stop(&w.state::<AppState>().srv), // never leave a hidden ComfyUI running
            _ => {}
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        // "Quit" in the tray ends with app.exit(), which does not always destroy the window first: stop ComfyUI here too
        // (app test 21 Oct: the engine kept 12 GB VRAM after Quit)
        .run(|app, ev| {
            if let tauri::RunEvent::Exit = ev {
                comfy::stop(&app.state::<AppState>().srv);
            }
        });
}
