//! Resumable downloads (HTTP Range) into a .part file, renamed when complete. Progress is emitted as "dl-progress" events.
use futures_util::StreamExt;
use serde::Serialize;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
};
use tauri::{AppHandle, Emitter};
use tokio::io::AsyncWriteExt;

#[derive(Clone, Serialize)]
pub struct Progress {
    pub id: String,
    pub done: u64,
    pub total: u64,
    pub mb_per_s: f64,
    /// "running" | "done" | "error" | "cancelled"
    pub state: String,
    pub message: String,
}

#[derive(Default, Clone)]
pub struct Downloads(pub Arc<Mutex<HashMap<String, Arc<AtomicBool>>>>);

impl Downloads {
    pub fn cancel(&self, id: &str) {
        if let Some(f) = self.0.lock().unwrap().get(id) {
            f.store(true, Ordering::SeqCst);
        }
    }
}

fn emit(app: &AppHandle, p: Progress) {
    let _ = app.emit("dl-progress", p);
}

/// Report a file that is already complete as done (no download).
pub fn done(app: &AppHandle, id: &str, size: u64) {
    emit(app, Progress { id: id.into(), done: size, total: size, mb_per_s: 0.0, state: "done".into(), message: String::new() });
}

/// Download `url` to `target` (resuming `target.part`). Returns when finished, failed or cancelled.
pub async fn fetch(app: AppHandle, dl: Downloads, id: String, url: String, target: PathBuf, size: u64) -> anyhow::Result<()> {
    let cancel = Arc::new(AtomicBool::new(false));
    dl.0.lock().unwrap().insert(id.clone(), cancel.clone());
    let res = run(&app, &id, &url, &target, size, &cancel).await;
    dl.0.lock().unwrap().remove(&id);
    let (state, message) = match &res {
        Ok(()) => ("done", String::new()),
        Err(e) if cancel.load(Ordering::SeqCst) => ("cancelled", e.to_string()),
        Err(e) => ("error", e.to_string()),
    };
    emit(&app, Progress { id, done: 0, total: size, mb_per_s: 0.0, state: state.into(), message });
    res
}

async fn run(app: &AppHandle, id: &str, url: &str, target: &PathBuf, size: u64, cancel: &AtomicBool) -> anyhow::Result<()> {
    if let Some(p) = target.parent() {
        tokio::fs::create_dir_all(p).await?;
    }
    let part = target.with_extension(format!("{}.part", target.extension().and_then(|e| e.to_str()).unwrap_or("bin")));
    let mut have = tokio::fs::metadata(&part).await.map(|m| m.len()).unwrap_or(0);
    let client = reqwest::Client::builder().user_agent("Fumika/0.1").build()?;
    let mut req = client.get(url);
    if have > 0 {
        req = req.header("Range", format!("bytes={have}-"));
    }
    let resp = req.send().await?.error_for_status()?;
    if have > 0 && resp.status() != reqwest::StatusCode::PARTIAL_CONTENT {
        have = 0; // server ignored the range -> start over
    }
    let total = resp.content_length().map(|l| l + have).unwrap_or(size);
    let mut file = tokio::fs::OpenOptions::new().create(true).write(true).append(have > 0).truncate(have == 0).open(&part).await?;
    let mut stream = resp.bytes_stream();
    let (mut done, start, mut last) = (have, std::time::Instant::now(), std::time::Instant::now());
    while let Some(chunk) = stream.next().await {
        if cancel.load(Ordering::SeqCst) {
            anyhow::bail!("cancelled");
        }
        let chunk = chunk?;
        file.write_all(&chunk).await?;
        done += chunk.len() as u64;
        if last.elapsed().as_millis() > 400 {
            last = std::time::Instant::now();
            let mbs = (done - have) as f64 / 1e6 / start.elapsed().as_secs_f64().max(0.001);
            emit(app, Progress { id: id.into(), done, total, mb_per_s: mbs, state: "running".into(), message: String::new() });
        }
    }
    file.flush().await?;
    drop(file);
    let got = tokio::fs::metadata(&part).await?.len();
    if total > 0 && got != total {
        anyhow::bail!("incomplete download ({got} of {total} bytes) - press download again to resume");
    }
    tokio::fs::rename(&part, target).await?;
    Ok(())
}
