//! Trainer section: the trainer plugins (MOSS LoRA Trainer, Anima LoRA Trainer) write every run into
//! models/loras/<family>_training/<name>/ - this module lists those runs (state from the log / saved files), and serves
//! their sample images through the `trainimg` URI scheme (only files below the training folders).
use crate::config::Config;
use serde::Serialize;
use std::path::{Path, PathBuf};

/// sub-folder of models/loras per trainer plugin
pub const FOLDERS: [(&str, &str); 4] = [("moss-lora-trainer", "moss_training"), ("anima-lora-trainer", "anima_training"),
    ("sdxl-lora-trainer", "sdxl_training"), ("slider-trainer", "slider_training")];

#[derive(Serialize, Debug, Default)]
pub struct LoraFile {
    pub name: String,
    pub path: String,
    pub size: u64,
    pub modified: i64,
}

#[derive(Serialize, Debug, Default)]
pub struct Run {
    pub plugin: String,
    pub name: String,
    pub dir: String,
    /// prepared (checked, never started) | starting | training | finished | failed
    pub state: String,
    pub step: Option<u64>,
    pub total: Option<u64>,
    pub remaining: Option<String>,
    pub loss: Option<String>,
    /// saved files / expected files (Anima: from the generated TOML, no log on Windows)
    pub saved: usize,
    pub expected: Option<usize>,
    pub files: Vec<LoraFile>,
    /// sample image paths (relative to the run folder) for the trainimg scheme
    pub samples: Vec<String>,
    pub modified: i64,
}

pub fn root(c: &Config) -> Option<PathBuf> {
    c.models_dir().map(|m| m.join("loras"))
}

fn mtime(p: &Path) -> i64 {
    std::fs::metadata(p).and_then(|m| m.modified()).ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok()).map(|d| d.as_secs() as i64).unwrap_or(0)
}

/// newest tqdm "steps: 42%|...| 714/1700 [21:27<29:18, 1.83s/it, avr_loss=0.244]" line of a kohya log
pub fn parse_steps(log: &str) -> Option<(u64, u64, String, Option<String>)> {
    // the bundled Anima slider trainer: "[slider] step 120/500  loss=0.01234  (98.1s, ...)"
    let sl = log.rfind("[slider] step ");
    // kohya ("steps: ...") or any other tqdm bar, e.g. ai-toolkit ("my_slider:  12%|#  | 60/500 [01:00<07:20, 1.0s/it, lr: 2.0e-04 loss: 1.2e-01]")
    // only tqdm-shaped lines ("...%|"): a plain log line with "steps:" in it must not hide newer progress
    // kohya's training bar ("steps: 33%|") wins; any other tqdm bar (ai-toolkit) only when there is none - kohya's caching and
    // sample bars ("100%| 49/49") must not read as training progress
    let line_start = |j: usize| log[..j].rfind(['\r', '\n']).map(|k| k + 1).unwrap_or(0);
    let kohya = log.match_indices("%|").map(|(j, _)| line_start(j)).filter(|&s| log[s..].trim_start().starts_with("steps:")).last();
    let tq = kohya.or_else(|| log.rfind("%|").map(line_start));
    if let Some(i) = sl.filter(|i| tq.map(|t| *i > t).unwrap_or(true)) {
        let seg = &log[i + 14..];
        let seg = &seg[..seg.find(['\r', '\n']).unwrap_or(seg.len())];
        let (frac, rest) = seg.split_once(' ').unwrap_or((seg, ""));
        let (a, b) = frac.split_once('/')?;
        let (a, b): (u64, u64) = (a.parse().ok()?, b.parse().ok()?);
        let loss = rest.split_once("loss=").map(|(_, r)| r.split_whitespace().next().unwrap_or("").to_string());
        // "(4.2s, ...)" = seconds of that step (it varies with the denoise stop) -> mean of the last 20 steps x steps left
        let secs: Vec<f64> = log.rsplit("[slider] step ").take(20).filter_map(|l| {
            l.split_once('(')?.1.split(['s', ',']).next()?.parse::<f64>().ok()
        }).collect();
        let rem = (!secs.is_empty()).then(|| {
            let r = (secs.iter().sum::<f64>() / secs.len() as f64 * b.saturating_sub(a) as f64) as u64;
            format!("{:02}:{:02}", r / 60, r % 60)
        }).unwrap_or_default();
        return Some((a, b, rem, loss));
    }
    let i = tq?;
    let seg = &log[i..];
    let seg = &seg[..seg.find(['\r', '\n']).unwrap_or(seg.len())];
    let after = seg.rsplit('|').next()?.trim();                    // "714/1700 [21:27<29:18, 1.83s/it, avr_loss=0.244]"
    let (frac, rest) = after.split_once(' ').unwrap_or((after, ""));
    let (a, b) = frac.split_once('/')?;
    let rem = rest.split_once('<').map(|(_, r)| r.split([',', ']']).next().unwrap_or("").trim().to_string()).unwrap_or_default();
    let loss = rest.split_once("avr_loss=").or_else(|| rest.split_once("loss: "))
        .map(|(_, r)| r.trim_end_matches(']').split([',', ']', ' ']).next().unwrap_or("").to_string());
    Some((a.trim().parse().ok()?, b.trim().parse().ok()?, rem, loss))
}

fn toml_num(t: &str, key: &str) -> Option<usize> {
    t.lines().find_map(|l| {
        let (k, v) = l.split_once('=')?;
        (k.trim() == key).then(|| v.trim().trim_matches('"').parse().ok()).flatten()
    })
}

pub fn read_run(plugin: &str, dir: &Path) -> Run {
    let mut r = Run { plugin: plugin.into(), name: dir.file_name().unwrap_or_default().to_string_lossy().into(),
                      dir: dir.display().to_string(), state: "prepared".into(), modified: mtime(dir), ..Default::default() };
    let mut tomls = vec![];
    let mut logs = vec![];
    for (sub, p) in walk(dir) {
        let n = p.file_name().unwrap_or_default().to_string_lossy().to_lowercase();
        r.modified = r.modified.max(mtime(&p));
        if n.ends_with(".safetensors") {
            r.files.push(LoraFile { name: p.file_name().unwrap().to_string_lossy().into(), path: p.display().to_string(),
                                    size: std::fs::metadata(&p).map(|m| m.len()).unwrap_or(0), modified: mtime(&p) });
        } else if [".png", ".jpg", ".jpeg", ".webp"].iter().any(|x| n.ends_with(x)) {
            r.samples.push(sub);
        } else if n.ends_with(".toml") {
            tomls.push(p);
        } else if n == "run_config.json" {
            // MOSS trainer: epochs + save_every of the run
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(&std::fs::read_to_string(&p).unwrap_or_default()) {
                if let (Some(ep), Some(ev)) = (v["epochs"].as_u64().or(v["steps"].as_u64()), v["save_every"].as_u64()) {
                    r.expected = Some(((ep / ev.max(1)) as usize).max(1));   // slider trainer: steps / save_every
                }
            }
        } else if n == "train_log.txt" || (n.starts_with("training_log_") && n.ends_with(".txt")) {
            logs.push(p);
        }
    }
    r.files.sort_by_key(|f| f.modified);
    r.samples.sort();
    r.saved = r.files.len();
    if let Some(t) = tomls.iter().max_by_key(|p| mtime(p)).and_then(|p| std::fs::read_to_string(p).ok()) {
        if let (Some(ep), Some(ev)) = (toml_num(&t, "max_train_epochs"), toml_num(&t, "save_every_n_epochs")) {
            r.expected = Some((ep / ev.max(1)).max(1));
        }
    }
    if let Some(log) = logs.iter().max_by_key(|p| mtime(p)).and_then(|p| std::fs::read(p).ok()) {
        let s = String::from_utf8_lossy(&log[log.len().saturating_sub(200_000)..]).to_string();
        r.state = if s.contains("TRAIN_EXIT 0") { "finished" } else if s.contains("TRAIN_EXIT ") { "failed" } else { "starting" }.into();
        if let Some((a, b, rem, loss)) = parse_steps(&s) {
            if r.state == "starting" { r.state = "training".into(); }
            (r.step, r.total, r.remaining, r.loss) = (Some(a), Some(b), Some(rem), loss);
        }
    } else if r.saved > 0 {
        // Anima on Windows trains in its own console window without a log: saved files tell the progress
        r.state = if r.expected.map(|x| r.saved >= x).unwrap_or(false) { "finished" } else { "training" }.into();
    }
    r
}

/// (path relative to `dir` with forward slashes, absolute path), two levels deep (samples live in <run>/sample/)
fn walk(dir: &Path) -> Vec<(String, PathBuf)> {
    let mut out = vec![];
    for f in std::fs::read_dir(dir).into_iter().flatten().flatten() {
        let p = f.path();
        let n = f.file_name().to_string_lossy().to_string();
        if p.is_dir() {
            for g in std::fs::read_dir(&p).into_iter().flatten().flatten() {
                if g.path().is_file() {
                    out.push((format!("{n}/{}", g.file_name().to_string_lossy()), g.path()));
                }
            }
        } else {
            out.push((n, p));
        }
    }
    out
}

pub fn runs(c: &Config, enabled: &[String]) -> Vec<Run> {
    let Some(root) = root(c) else { return vec![] };
    let mut out = vec![];
    for (plugin, sub) in FOLDERS {
        if !enabled.iter().any(|p| p == plugin) {
            continue;
        }
        for d in std::fs::read_dir(root.join(sub)).into_iter().flatten().flatten() {
            if d.path().is_dir() {
                out.push(read_run(plugin, &d.path()));
            }
        }
    }
    out.sort_by_key(|r| -r.modified);
    out
}

/// a sample image below models/loras/<family>_training only (query: path=<plugin folder>/<run>/<file>)
pub fn sample(c: &Config, rel: &str) -> anyhow::Result<(String, Vec<u8>)> {
    let root = root(c).ok_or_else(|| anyhow::anyhow!("not set up"))?;
    let p = root.join(rel).canonicalize()?;
    let ok = FOLDERS.iter().any(|(_, sub)| root.join(sub).canonicalize().map(|r| p.starts_with(r)).unwrap_or(false));
    if !ok {
        anyhow::bail!("outside the training folders");
    }
    let ct = match p.extension().and_then(|x| x.to_str()).unwrap_or("").to_lowercase().as_str() {
        "jpg" | "jpeg" => "image/jpeg",
        "webp" => "image/webp",
        _ => "image/png",
    };
    Ok((ct.into(), std::fs::read(p)?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tqdm_line() {
        let log = "x\rsteps:  33%|███▎      | 705/2128 [21:27<43:18,  1.83s/it, avr_loss=0.244]\rsteps:  33%|███▎      | 706/2128 [21:29<43:16,  1.83s/it, avr_loss=0.243]";
        let (a, b, rem, loss) = parse_steps(log).unwrap();
        assert_eq!((a, b, rem.as_str(), loss.as_deref()), (706, 2128, "43:16", Some("0.243")));
        assert!(parse_steps("no progress yet").is_none());
        // a later non-tqdm line with "steps:" does not hide the progress bar
        let (a, _, _, _) = parse_steps("steps:  10%|#  | 170/1700 [01:00<09:00, 1.0s/it, avr_loss=0.3]
INFO max_train_steps: 1700
").unwrap();
        assert_eq!(a, 170);
        // a later caching / sample bar does not replace kohya's training bar
        let (a, b, _, _) = parse_steps("steps:  10%|#  | 170/1700 [01:00<09:00, 1.0s/it, avr_loss=0.3]\rcaching latents: 100%|##| 49/49 [00:05<00:00]").unwrap();
        assert_eq!((a, b), (170, 1700));
    }

    #[test]
    fn slider_lines() {
        let log = "[slider] training 500 steps\n[slider] step 99/500  loss=0.02000  (0.5s)\n[slider] step 100/500  loss=0.01234  (1.5s, stop=12, sigma=0.500)\n";
        let (a, b, rem, loss) = parse_steps(log).unwrap();
        assert_eq!((a, b, rem.as_str(), loss.as_deref()), (100, 500, "06:40", Some("0.01234")));   // mean of 0.5 s and 1.5 s x 400 steps left
        let aitk = "Loading\nmy_slider:  12%|#2        | 60/500 [01:00<07:20,  1.00s/it, lr: 2.0e-04 loss: 1.234e-01]\rmy_slider:  12%|#2        | 61/500 [01:01<07:19,  1.00s/it, lr: 2.0e-04 loss: 1.111e-01]";
        let (a, b, rem, loss) = parse_steps(aitk).unwrap();
        assert_eq!((a, b, rem.as_str(), loss.as_deref()), (61, 500, "07:19", Some("1.111e-01")));
    }

    #[test]
    fn run_folder() {
        let d = std::env::temp_dir().join(format!("fumika_run_{}", uuid::Uuid::new_v4().simple()));
        std::fs::create_dir_all(d.join("sample")).unwrap();
        std::fs::write(d.join("training_config_1.toml"), "max_train_epochs = 12\nsave_every_n_epochs = 4\n").unwrap();
        std::fs::write(d.join("fumika-000004.safetensors"), b"x").unwrap();
        std::fs::write(d.join("sample").join("fumika_e000004_00.png"), b"x").unwrap();
        let r = read_run("anima-lora-trainer", &d);
        assert_eq!((r.state.as_str(), r.saved, r.expected), ("training", 1, Some(3)));
        assert_eq!(r.samples, vec!["sample/fumika_e000004_00.png".to_string()]);
        std::fs::write(d.join("train_log.txt"), "steps: 100%|##| 1700/1700 [1:00:00<00:00, 2.1s/it, avr_loss=0.2]\nTRAIN_EXIT 0\n").unwrap();
        let r = read_run("moss-lora-trainer", &d);
        assert_eq!((r.state.as_str(), r.step, r.total), ("finished", Some(1700), Some(1700)));
        let _ = std::fs::remove_dir_all(d);
    }
}
