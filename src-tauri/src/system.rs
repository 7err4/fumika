//! System check for the setup wizard: NVIDIA GPU + VRAM (nvidia-smi) and free disk space.
use serde::Serialize;
use std::path::Path;
use std::process::Command;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
pub const NO_WINDOW: u32 = 0x0800_0000;

#[derive(Serialize, Default)]
pub struct Gpu {
    pub name: String,
    pub vram_mb: u64,
    pub driver: String,
}

#[derive(Serialize)]
pub struct Report {
    pub gpus: Vec<Gpu>,
    pub free_gb: Option<f64>,
    /// short verdict for the wizard
    pub verdict: String,
    pub recommended_base: String,
}

pub fn gpus() -> Vec<Gpu> {
    let mut c = Command::new("nvidia-smi");
    c.args(["--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"]);
    #[cfg(windows)]
    c.creation_flags(NO_WINDOW);
    let Ok(out) = c.output() else { return vec![] };
    String::from_utf8_lossy(&out.stdout)
        .lines()
        .filter_map(|l| {
            let p: Vec<&str> = l.split(',').map(|s| s.trim()).collect();
            (p.len() >= 3).then(|| Gpu { name: p[0].into(), vram_mb: p[1].parse().unwrap_or(0), driver: p[2].into() })
        })
        .collect()
}

pub fn free_gb(dir: &Path) -> Option<f64> {
    // walk up to an existing folder (the install dir may not exist yet)
    let mut d = dir.to_path_buf();
    while !d.exists() {
        d = d.parent()?.to_path_buf();
    }
    fs2::available_space(&d).ok().map(|b| b as f64 / 1e9)
}

pub fn report(dir: &Path) -> Report {
    let gpus = gpus();
    let free = free_gb(dir);
    let vram = gpus.iter().map(|g| g.vram_mb).max().unwrap_or(0);
    let verdict = if gpus.is_empty() {
        "No NVIDIA GPU found. Fumika needs an NVIDIA graphics card.".to_string()
    } else if vram < 12_000 {
        format!("{} MB VRAM - probably too little for MOSS-Image (12 GB minimum, 16+ recommended).", vram)
    } else if free.unwrap_or(0.0) < 30.0 {
        format!("Only {:.0} GB free here - about 25 GB are needed. Pick another folder.", free.unwrap_or(0.0))
    } else {
        "Ready.".to_string()
    };
    let recommended_base = if vram >= 24_000 { "moss_base_bf16" } else { "moss_base_int8" }.to_string();
    Report { gpus, free_gb: free, verdict, recommended_base }
}

/// VRAM in use / total of the first NVIDIA GPU in MB (for the engine line in the rail).
pub fn vram() -> Option<(u64, u64)> {
    let mut c = Command::new("nvidia-smi");
    c.args(["--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"]);
    #[cfg(windows)]
    c.creation_flags(NO_WINDOW);
    let out = c.output().ok()?;
    let line = String::from_utf8_lossy(&out.stdout).lines().next()?.to_string();
    let mut p = line.split(',').map(|s| s.trim().parse::<u64>().ok());
    Some((p.next()??, p.next()??))
}
