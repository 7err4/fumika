//! GPU lock between training and rendering: while a LoRA training runs (a kohya / sd-scripts `*train_network*` process -
//! the trainer plugins start them in their own window - or an ai-toolkit `run.py <config>.yaml`), the render queue claims no new jobs, so pages and assets do not fight
//! the training for VRAM. Jobs of the "Trainer" project (check / start / epoch test) still run. The user can override it
//! ("render anyway"); the override ends with the training.
use serde::Serialize;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

#[derive(Serialize, Clone, Debug, PartialEq, Default)]
pub struct Gate {
    /// what is training (script / output name), None = no training found
    pub training: Option<String>,
    /// the user said "render anyway"
    pub overridden: bool,
    /// the queue holds back new render jobs right now
    pub paused: bool,
}

#[derive(Default)]
pub struct GpuLock {
    overridden: AtomicBool,
    training: Mutex<Option<String>>,
    last_scan: Mutex<Option<Instant>>,
}

const SCAN_EVERY: Duration = Duration::from_secs(8);

/// a training among process command lines -> a short label ("anima_train_network.py · fumika_v2")
pub fn training_in(cmdlines: &[String]) -> Option<String> {
    cmdlines.iter().find_map(|c| {
        let toks: Vec<&str> = c.split_whitespace().map(|t| t.trim_matches('"')).collect();
        let file = |t: &str| t.rsplit(['/', '\\']).next().unwrap_or(t).to_lowercase();
        // ai-toolkit (ostris): "python run.py <config>.yaml" -> "ai-toolkit · <config>"
        if toks.iter().any(|t| file(t) == "run.py") {
            if let Some(cfg) = toks.iter().map(|t| file(t)).find(|f| f.ends_with(".yaml") || f.ends_with(".yml")) {
                return Some(format!("ai-toolkit · {}", cfg.trim_end_matches(".yaml").trim_end_matches(".yml")));
            }
        }
        let script = toks.iter().find(|t| {
            let f = t.rsplit(['/', '\\']).next().unwrap_or(t).to_lowercase();
            f.contains("train_network") && f.ends_with(".py")
        })?;
        let script = script.rsplit(['/', '\\']).next().unwrap_or(script).to_string();
        let name = toks.windows(2).find(|w| w[0] == "--output_name").map(|w| w[1].to_string());
        Some(match name {
            Some(n) => format!("{script} · {n}"),
            None => script,
        })
    })
}

impl GpuLock {
    pub fn gate(&self) -> Gate {
        let training = self.training.lock().unwrap().clone();
        let overridden = self.overridden.load(Ordering::Relaxed);
        Gate { paused: training.is_some() && !overridden, training, overridden }
    }

    pub fn set_override(&self, on: bool) {
        self.overridden.store(on, Ordering::Relaxed);
    }

    /// new training state; returns true when the gate changed. A finished training also ends the override.
    pub fn update(&self, training: Option<String>) -> bool {
        let mut t = self.training.lock().unwrap();
        if *t == training {
            return false;
        }
        if training.is_none() {
            self.overridden.store(false, Ordering::Relaxed);
        }
        *t = training;
        true
    }

    /// rescan the processes at most every few seconds; returns true when the gate changed
    pub async fn refresh(&self) -> bool {
        {
            let mut last = self.last_scan.lock().unwrap();
            if last.map(|l| l.elapsed() < SCAN_EVERY).unwrap_or(false) {
                return false;
            }
            *last = Some(Instant::now());
        }
        let found = training_in(&python_cmdlines().await);
        self.update(found)
    }
}

/// command lines of the running python processes (no console window flashes on Windows)
async fn python_cmdlines() -> Vec<String> {
    #[cfg(windows)]
    let out = {
        let mut cmd = tokio::process::Command::new("powershell");
        cmd.args(["-NoProfile", "-NonInteractive", "-Command",
                  "Get-CimInstance Win32_Process -Filter \"name like 'python%'\" | ForEach-Object { $_.CommandLine }"]);
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        cmd.output().await
    };
    #[cfg(not(windows))]
    let out = tokio::process::Command::new("ps").args(["-eo", "args"]).output().await;
    match out {
        Ok(o) => String::from_utf8_lossy(&o.stdout).lines().map(str::trim).filter(|l| !l.is_empty()).map(String::from).collect(),
        Err(_) => vec![],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_kohya_trainings() {
        let cl = |s: &str| vec![s.to_string()];
        assert_eq!(training_in(&cl(r#""C:\x\venv\Scripts\python.exe" "C:\x\sd-scripts\anima_train_network.py" --config_file "D:\a.toml""#)),
                   Some("anima_train_network.py".into()));
        assert_eq!(training_in(&cl("python -u moss_image_train_network.py --output_name terra_moss_v1 --lr 1e-4")),
                   Some("moss_image_train_network.py · terra_moss_v1".into()));
        assert_eq!(training_in(&cl("python main.py --port 8291")), None);
        assert_eq!(training_in(&cl(r#"venv/Scripts/python.exe -u run.py "C:\x\charref_v2.yaml""#)), Some("ai-toolkit · charref_v2".into()));
        assert_eq!(training_in(&cl("python run.py --port 8000")), None);
        assert_eq!(training_in(&[]), None);
    }

    #[test]
    fn gate_pauses_until_override_or_end() {
        let g = GpuLock::default();
        assert!(!g.gate().paused);
        assert!(g.update(Some("anima_train_network.py".into())));
        assert!(g.gate().paused);
        assert!(!g.update(Some("anima_train_network.py".into())), "same training, no change");
        g.set_override(true);
        assert_eq!(g.gate(), Gate { training: Some("anima_train_network.py".into()), overridden: true, paused: false });
        assert!(g.update(None));
        assert_eq!(g.gate(), Gate::default(), "the override ends with the training");
    }
}
