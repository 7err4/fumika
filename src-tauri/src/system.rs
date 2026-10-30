//! System check for the setup wizard: NVIDIA / Linux AMD GPU + VRAM and free disk space.
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

fn nvidia_gpus() -> Vec<Gpu> {
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

/// Prefer NVIDIA on mixed systems, preserving the existing CUDA installation.
pub fn use_rocm() -> bool {
    prefer_rocm(cfg!(target_os = "linux"), !nvidia_gpus().is_empty(), !amd_gpus().is_empty())
}

fn prefer_rocm(linux: bool, nvidia: bool, amd: bool) -> bool {
    linux && !nvidia && amd
}

pub fn gpus() -> Vec<Gpu> {
    let mut g = nvidia_gpus();
    g.extend(amd_gpus());
    g
}

/// Read DRM devices instead of relying on a particular ROCm CLI version or GPU model.
fn amd_gpus() -> Vec<Gpu> {
    if !cfg!(target_os = "linux") { return vec![]; }
    amd_gpus_at(Path::new("/sys/class/drm"))
}

fn amd_gpus_at(root: &Path) -> Vec<Gpu> {
    let Ok(entries) = std::fs::read_dir(root) else { return vec![] };
    entries.flatten().filter_map(|e| {
        let name = e.file_name();
        let suffix = name.to_str()?.strip_prefix("card")?;
        if suffix.is_empty() || !suffix.chars().all(|c| c.is_ascii_digit()) { return None; }
        let d = e.path().join("device");
        if std::fs::read_to_string(d.join("vendor")).ok()?.trim() != "0x1002" { return None; }
        let bytes = std::fs::read_to_string(d.join("mem_info_vram_total")).ok()
            .and_then(|v| v.trim().parse::<u64>().ok()).unwrap_or(0);
        Some(Gpu { name: format!("AMD GPU ({})", std::fs::read_to_string(d.join("device")).unwrap_or_default().trim()),
            vram_mb: bytes / 1024 / 1024, driver: "amdgpu / ROCm".into() })
    }).collect()
}

pub const ROCM_HELP: &str = "ROCm unavailable: install a supported AMD amdgpu/ROCm driver, check GPU/OS compatibility and access to /dev/kfd and /dev/dri/render* (render/video groups), then run rocminfo. See https://rocm.docs.amd.com/ .";

pub fn rocm_diagnostic() -> Option<String> {
    if !use_rocm() { return None; }
    match std::fs::OpenOptions::new().read(true).write(true).open("/dev/kfd") {
        Ok(_) => None,
        Err(e) => Some(format!("{ROCM_HELP} /dev/kfd: {e}")),
    }
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
    let verdict = if let Some(problem) = rocm_diagnostic() {
        problem
    } else if gpus.is_empty() {
        "No NVIDIA or Linux AMD GPU found.".to_string()
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

#[cfg(test)]
mod tests {
    #[test]
    fn backend_selection_preserves_nvidia_and_no_gpu_paths() {
        assert!(super::prefer_rocm(true, false, true));
        assert!(!super::prefer_rocm(true, true, true));
        assert!(!super::prefer_rocm(true, true, false));
        assert!(!super::prefer_rocm(true, false, false));
        assert!(!super::prefer_rocm(false, false, true));
    }

    #[test]
    fn drm_detection_filters_connectors_and_other_vendors() {
        let root = std::env::temp_dir().join(format!("fumika-drm-{}", uuid::Uuid::new_v4()));
        for (name, vendor) in [("card0", "0x1002"), ("card0-DP-1", "0x1002"), ("renderD128", "0x1002"), ("card1", "0x10de")] {
            let d = root.join(name).join("device");
            std::fs::create_dir_all(&d).unwrap();
            std::fs::write(d.join("vendor"), vendor).unwrap();
            std::fs::write(d.join("device"), "0x1234").unwrap();
            std::fs::write(d.join("mem_info_vram_total"), "17179869184").unwrap();
        }
        let g = super::amd_gpus_at(&root);
        assert_eq!(g.len(), 1);
        assert_eq!(g[0].vram_mb, 16384);
        assert!(g[0].name.contains("0x1234"));
        std::fs::remove_dir_all(root).unwrap();
    }
}
