//! Persistent render queue (SQLite, %APPDATA%/Fumika/studio.db) and the dispatcher that feeds it to a backend.
//! ComfyUI's own queue lives in memory and is lost on restart, so this is the source of truth: a job keeps its id, its
//! graph and its state across app restarts, and the dispatcher hands ComfyUI one prompt at a time (job id = prompt_id, so a
//! resubmit is idempotent and the history lookup needs no mapping).
use crate::comfy;
use rusqlite::{Connection, OptionalExtension, params};
use serde::Serialize;
use serde_json::Value;
use std::path::Path;
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, Manager};

#[derive(Serialize, Clone, Debug)]
pub struct Job {
    pub id: String,
    pub project: String,
    pub label: String,
    pub state: String, // queued | running | done | failed | cancelled
    pub priority: i64,
    pub attempts: i64,
    /// ComfyUI history outputs of the finished prompt ({node_id: {images: [...]}})
    pub outputs: Value,
    pub error: Option<String>,
    pub created: i64,
    pub updated: i64,
}

/// Where a job runs. Local = the bundled ComfyUI; more GPUs and remote workers become further variants.
#[derive(Clone, Debug)]
pub enum Backend {
    Local { port: u16 },
}

enum Poll {
    Waiting,
    Done(Value),
    Failed(String),
    Unknown,
}

impl Backend {
    async fn ready(&self) -> bool {
        match self {
            Backend::Local { port } => comfy::healthy(*port).await,
        }
    }
    async fn submit(&self, id: &str, graph: &Value) -> anyhow::Result<()> {
        match self {
            Backend::Local { port } => {
                comfy::request(*port, "POST", "/prompt", Some(serde_json::json!({"prompt": graph, "prompt_id": id}))).await?;
                Ok(())
            }
        }
    }
    async fn poll(&self, id: &str) -> anyhow::Result<Poll> {
        match self {
            Backend::Local { port } => {
                let h = comfy::request(*port, "GET", &format!("/history/{id}"), None).await?;
                if let Some(it) = h.get(id) {
                    let msgs = it.pointer("/status/messages").and_then(|m| m.as_array()).cloned().unwrap_or_default();
                    if let Some(err) = msgs.iter().find(|m| m.get(0).and_then(|x| x.as_str()) == Some("execution_error")) {
                        let msg = err.pointer("/1/exception_message").and_then(|x| x.as_str()).unwrap_or("execution error");
                        return Ok(Poll::Failed(msg.to_string()));
                    }
                    if it.pointer("/status/completed").and_then(|x| x.as_bool()) == Some(true) {
                        return Ok(Poll::Done(it.get("outputs").cloned().unwrap_or(Value::Null)));
                    }
                    return Ok(Poll::Waiting);
                }
                let q = comfy::request(*port, "GET", "/queue", None).await?;
                let listed = |k: &str| q.get(k).and_then(|v| v.as_array()).map(|a| a.iter().any(|e| e.get(1).and_then(|x| x.as_str()) == Some(id))).unwrap_or(false);
                Ok(if listed("queue_running") || listed("queue_pending") { Poll::Waiting } else { Poll::Unknown })
            }
        }
    }
    async fn interrupt(&self, id: &str) {
        match self {
            Backend::Local { port } => {
                let _ = comfy::request(*port, "POST", "/interrupt", Some(serde_json::json!({"prompt_id": id}))).await;
                let _ = comfy::request(*port, "POST", "/queue", Some(serde_json::json!({"delete": [id]}))).await;
            }
        }
    }
}

pub struct Queue {
    db: Mutex<Connection>,
}

fn now() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0)
}

const COLS: &str = "id, project, label, state, priority, attempts, outputs, error, created, updated";

fn row(r: &rusqlite::Row) -> rusqlite::Result<Job> {
    let outputs: Option<String> = r.get(6)?;
    Ok(Job {
        id: r.get(0)?,
        project: r.get(1)?,
        label: r.get(2)?,
        state: r.get(3)?,
        priority: r.get(4)?,
        attempts: r.get(5)?,
        outputs: outputs.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null),
        error: r.get(7)?,
        created: r.get(8)?,
        updated: r.get(9)?,
    })
}

impl Queue {
    pub fn open(path: &Path) -> anyhow::Result<Self> {
        if let Some(d) = path.parent() {
            std::fs::create_dir_all(d)?;
        }
        let c = Connection::open(path)?;
        c.execute_batch(
            "PRAGMA journal_mode=WAL;
             CREATE TABLE IF NOT EXISTS jobs (
               id TEXT PRIMARY KEY, project TEXT NOT NULL, label TEXT NOT NULL, graph TEXT NOT NULL,
               state TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
               outputs TEXT, error TEXT, created INTEGER NOT NULL, updated INTEGER NOT NULL);
             CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, priority, created);",
        )?;
        Ok(Self { db: Mutex::new(c) })
    }

    pub fn add(&self, project: &str, label: &str, graph: &Value, priority: i64) -> anyhow::Result<String> {
        let id = uuid::Uuid::new_v4().to_string();
        let t = now();
        self.db.lock().unwrap().execute(
            "INSERT INTO jobs (id, project, label, graph, state, priority, created, updated) VALUES (?1, ?2, ?3, ?4, 'queued', ?5, ?6, ?6)",
            params![id, project, label, graph.to_string(), priority, t],
        )?;
        Ok(id)
    }

    fn graph(&self, id: &str) -> Option<Value> {
        let g: String = self.db.lock().unwrap().query_row("SELECT graph FROM jobs WHERE id = ?1", [id], |r| r.get(0)).ok()?;
        serde_json::from_str(&g).ok()
    }

    pub fn get(&self, id: &str) -> anyhow::Result<Option<Job>> {
        Ok(self.db.lock().unwrap().query_row(&format!("SELECT {COLS} FROM jobs WHERE id = ?1"), [id], row).optional()?)
    }

    pub fn list(&self, project: Option<&str>) -> anyhow::Result<Vec<Job>> {
        let db = self.db.lock().unwrap();
        let mut st = db.prepare(&format!("SELECT {COLS} FROM jobs WHERE (?1 IS NULL OR project = ?1) ORDER BY created, rowid"))?;
        let jobs = st.query_map([project], row)?.collect::<Result<Vec<_>, _>>()?;
        Ok(jobs)
    }

    fn set_state(&self, id: &str, state: &str, outputs: Option<&Value>, error: Option<&str>) -> anyhow::Result<()> {
        self.db.lock().unwrap().execute(
            "UPDATE jobs SET state = ?2, outputs = COALESCE(?3, outputs), error = ?4, updated = ?5 WHERE id = ?1",
            params![id, state, outputs.map(|o| o.to_string()), error, now()],
        )?;
        Ok(())
    }

    /// Back into the queue (retry of a failed / cancelled job, or a running one ComfyUI no longer knows).
    pub fn requeue(&self, id: &str) -> anyhow::Result<()> {
        self.set_state(id, "queued", None, None)
    }

    /// Cancel a job; returns true if it was running (the caller interrupts the backend).
    pub fn cancel(&self, id: &str) -> anyhow::Result<bool> {
        let was = self.get(id)?.map(|j| j.state).unwrap_or_default();
        if was == "queued" || was == "running" {
            self.set_state(id, "cancelled", None, None)?;
        }
        Ok(was == "running")
    }

    /// Next queued job (highest priority, oldest first) -> running, with its graph. `trainer_only`: while a training holds
    /// the GPU only the trainer's own small jobs (check / start / epoch test) may run.
    fn claim(&self, trainer_only: bool) -> anyhow::Result<Option<(String, Value)>> {
        let db = self.db.lock().unwrap();
        let next: Option<(String, String)> = db
            .query_row("SELECT id, graph FROM jobs WHERE state = 'queued' AND (?1 = 0 OR project = 'Trainer') ORDER BY priority DESC, created, rowid LIMIT 1",
                       [trainer_only as i64], |r| Ok((r.get(0)?, r.get(1)?)))
            .optional()?;
        let Some((id, graph)) = next else { return Ok(None) };
        db.execute("UPDATE jobs SET state = 'running', attempts = attempts + 1, error = NULL, updated = ?2 WHERE id = ?1", params![id, now()])?;
        Ok(Some((id, serde_json::from_str(&graph)?)))
    }

    /// Sampler passes of a job: the page node samples `versions` times (1 for graphs without that input).
    fn passes(&self, id: &str) -> u32 {
        let graph: Option<String> = self.db.lock().unwrap().query_row("SELECT graph FROM jobs WHERE id = ?1", [id], |r| r.get(0)).optional().ok().flatten();
        let g: Value = graph.and_then(|g| serde_json::from_str(&g).ok()).unwrap_or(Value::Null);
        g.as_object()
            .and_then(|nodes| nodes.values().find_map(|n| n.pointer("/inputs/versions").and_then(|v| v.as_u64())))
            .map(|v| v.max(1) as u32)
            .unwrap_or(1)
    }

    /// queued jobs that are not the trainer's own (the ones a training holds back)
    fn queued_renders(&self) -> i64 {
        self.db.lock().unwrap()
            .query_row("SELECT COUNT(*) FROM jobs WHERE state = 'queued' AND project != 'Trainer'", [], |r| r.get(0)).unwrap_or(0)
    }

    fn running(&self) -> anyhow::Result<Option<String>> {
        Ok(self.db.lock().unwrap().query_row("SELECT id FROM jobs WHERE state = 'running' ORDER BY updated LIMIT 1", [], |r| r.get(0)).optional()?)
    }
}

fn emit(app: &AppHandle, q: &Queue, id: &str) {
    if let Ok(Some(j)) = q.get(id) {
        let _ = app.emit("job-update", j);
    }
}

/// Dispatcher loop: one prompt at a time on the backend. A job that is 'running' after an app restart is polled first
/// (ComfyUI may have finished it meanwhile) and requeued if ComfyUI no longer knows it.
pub fn spawn_dispatcher(app: AppHandle, backend: impl Fn(&AppHandle) -> Backend + Send + 'static) {
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_millis(1500)).await;
            let b = backend(&app);
            if !b.ready().await {
                continue;
            }
            let q = app.state::<Queue>();
            let lock = app.state::<crate::gpulock::GpuLock>();
            // look for a training only when it matters: render jobs are waiting, or a training is still holding them back
            if (q.queued_renders() > 0 || lock.gate().training.is_some()) && lock.refresh().await {
                let _ = app.emit("queue-gate", lock.gate());
            }
            let current = match q.running() {
                Ok(Some(id)) => Some(id),
                Ok(None) => match q.claim(lock.gate().paused) {
                    Ok(Some((id, graph))) => {
                        emit(&app, &q, &id);
                        if let Err(err) = b.submit(&id, &graph).await {
                            let _ = q.set_state(&id, "failed", None, Some(&err.to_string()));
                            emit(&app, &q, &id);
                            continue;
                        }
                        Some(id)
                    }
                    _ => None,
                },
                Err(_) => None,
            };
            let Some(id) = current else { continue };
            match b.poll(&id).await {
                Ok(Poll::Done(out)) => {
                    // mark the pictures as AI-generated before anyone sees the job as done (exports copy the marked files)
                    let c = app.state::<crate::AppState>().cfg.lock().unwrap().clone();
                    let g = q.graph(&id);
                    let o = out.clone();
                    let _ = tokio::task::spawn_blocking(move || crate::aimark::mark_outputs(&c, &o, g.as_ref())).await;
                    let _ = q.set_state(&id, "done", Some(&out), None);
                    emit(&app, &q, &id);
                }
                Ok(Poll::Failed(msg)) => {
                    let _ = q.set_state(&id, "failed", None, Some(&msg));
                    emit(&app, &q, &id);
                }
                Ok(Poll::Unknown) => {
                    let _ = q.requeue(&id);
                    emit(&app, &q, &id);
                }
                Ok(Poll::Waiting) | Err(_) => {}
            }
        }
    });
}

/// Sampler progress of the running job, from ComfyUI's websocket. Prompts are submitted without a client_id, so ComfyUI
/// broadcasts their progress to every socket and the stream survives app restarts. A step counter that drops back means
/// the page node started its next version.
#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct Progress {
    pub id: String,
    pub step: u32,
    pub steps: u32,
    pub pass: u32,
    pub passes: u32,
}

#[derive(Default)]
struct Tracker {
    id: String,
    last: u32,
    pass: u32,
    passes: u32,
}

impl Tracker {
    /// one websocket message -> progress to emit (None for messages that are not sampler steps)
    fn feed(&mut self, msg: &Value, passes: impl Fn(&str) -> u32) -> Option<Progress> {
        let data = msg.get("data")?;
        let pid = data.get("prompt_id").and_then(|x| x.as_str())?;
        match msg.get("type").and_then(|t| t.as_str())? {
            "execution_start" => {
                *self = Tracker { id: pid.to_string(), last: 0, pass: 1, passes: passes(pid) };
                None
            }
            "progress" => {
                if self.id != pid {
                    *self = Tracker { id: pid.to_string(), last: 0, pass: 1, passes: passes(pid) };
                }
                let step = data.get("value")?.as_u64()? as u32;
                let steps = data.get("max")?.as_u64()? as u32;
                if step < self.last {
                    self.pass += 1;
                }
                self.last = step;
                Some(Progress { id: pid.to_string(), step, steps, pass: self.pass, passes: self.passes.max(self.pass) })
            }
            _ => None,
        }
    }
}

pub fn spawn_progress(app: AppHandle, port: impl Fn(&AppHandle) -> u16 + Send + 'static) {
    use futures_util::StreamExt;
    tauri::async_runtime::spawn(async move {
        let mut t = Tracker::default();
        loop {
            let url = format!("ws://127.0.0.1:{}/ws?clientId=fumika", port(&app));
            if let Ok((mut ws, _)) = tokio_tungstenite::connect_async(url).await {
                while let Some(Ok(m)) = ws.next().await {
                    let Ok(text) = m.into_text() else { continue };
                    let Ok(v) = serde_json::from_str::<Value>(&text) else { continue };
                    let q = app.state::<Queue>();
                    if let Some(p) = t.feed(&v, |id| q.passes(id)) {
                        let pass = if p.passes > 1 { format!("v{} · ", p.pass) } else { String::new() };
                        crate::shell::tray_status(&app, Some(format!("{pass}{}/{}", p.step, p.steps)));
                        let _ = app.emit("job-progress", p);
                    } else if v.get("type").and_then(|t| t.as_str()) == Some("status")
                        && v.pointer("/data/status/exec_info/queue_remaining").and_then(|x| x.as_u64()) == Some(0)
                    {
                        crate::shell::tray_status(&app, None);
                    }
                }
            }
            tokio::time::sleep(Duration::from_secs(2)).await;
        }
    });
}

pub async fn interrupt(b: &Backend, id: &str) {
    b.interrupt(id).await;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn add_claim_finish_cycle() {
        let dir = std::env::temp_dir().join(format!("moss_q_{}", uuid::Uuid::new_v4()));
        let q = Queue::open(&dir.join("studio.db")).unwrap();
        let a = q.add("p", "page 1", &serde_json::json!({"1": {}}), 0).unwrap();
        let b = q.add("p", "page 2", &serde_json::json!({"2": {}}), 5).unwrap();
        let (first, _) = q.claim(false).unwrap().unwrap();
        assert_eq!(first, b, "higher priority first");
        assert_eq!(q.running().unwrap().as_deref(), Some(b.as_str()));
        q.set_state(&b, "done", Some(&serde_json::json!({"9": {"images": []}})), None).unwrap();
        assert!(q.cancel(&a).is_ok());
        assert_eq!(q.get(&a).unwrap().unwrap().state, "cancelled");
        q.requeue(&a).unwrap();
        let (second, _) = q.claim(false).unwrap().unwrap();
        assert_eq!(second, a);
        assert_eq!(q.get(&a).unwrap().unwrap().attempts, 1);
        assert_eq!(q.list(Some("p")).unwrap().len(), 2);
        drop(q);
        let reopened = Queue::open(&dir.join("studio.db")).unwrap();
        assert_eq!(reopened.running().unwrap().as_deref(), Some(a.as_str()), "running state survives a restart");
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn training_holds_back_renders_only() {
        let dir = std::env::temp_dir().join(format!("moss_q_{}", uuid::Uuid::new_v4()));
        let q = Queue::open(&dir.join("studio.db")).unwrap();
        let page = q.add("Deadline", "Page 1", &serde_json::json!({}), 0).unwrap();
        assert_eq!(q.queued_renders(), 1);
        assert!(q.claim(true).unwrap().is_none(), "a page waits while a training runs");
        let check = q.add("Trainer", "train-check x", &serde_json::json!({}), 5).unwrap();
        assert_eq!(q.claim(true).unwrap().unwrap().0, check, "trainer jobs still run");
        q.set_state(&check, "done", None, None).unwrap();
        assert_eq!(q.claim(false).unwrap().unwrap().0, page, "the page runs once the training is over");
        drop(q);
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn progress_counts_versions() {
        let mut t = Tracker::default();
        let msg = |ty: &str, v: u32| serde_json::json!({"type": ty, "data": {"prompt_id": "a", "value": v, "max": 50, "node": "1"}});
        assert_eq!(t.feed(&msg("execution_start", 0), |_| 3), None);
        assert_eq!(t.feed(&msg("progress", 30), |_| 3).unwrap().pass, 1);
        let p = t.feed(&msg("progress", 50), |_| 3).unwrap();
        assert_eq!((p.step, p.steps, p.pass, p.passes), (50, 50, 1, 3));
        let p = t.feed(&msg("progress", 1), |_| 3).unwrap();
        assert_eq!((p.step, p.pass), (1, 2), "a dropping step counter is the next version");
        assert!(t.feed(&serde_json::json!({"type": "status", "data": {}}), |_| 3).is_none());
        let g = serde_json::json!({"1": {"class_type": "MossEasyDoujinPage", "inputs": {"versions": 3}}});
        let dir = std::env::temp_dir().join(format!("moss_q_{}", uuid::Uuid::new_v4()));
        let q = Queue::open(&dir.join("studio.db")).unwrap();
        let id = q.add("p", "page 1", &g, 0).unwrap();
        assert_eq!(q.passes(&id), 3);
        drop(q);
        let _ = std::fs::remove_dir_all(dir);
    }
}
