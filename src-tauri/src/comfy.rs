//! Bundled ComfyUI: install the engine (Windows: the portable archive; Linux: ComfyUI source + its own Python via uv), copy
//! our node packs, start / stop the hidden server.
use crate::config::Config;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[derive(Default, Clone)]
/// the engine process this app started, and the pid of an engine taken over from a crashed earlier run (see `adopt`)
pub struct Server(pub Arc<Mutex<Option<Child>>>, pub Arc<Mutex<Option<u32>>>);

/// the engine's Python: the portable build's embedded one on Windows, the venv uv creates on Linux
pub fn python(dir: &Path) -> PathBuf {
    if cfg!(windows) { dir.join("python_embeded").join("python.exe") } else { dir.join("venv").join("bin").join("python") }
}

/// Linux: written as the last step of install_linux - venv/bin/python exists long before PyTorch is in it
const LINUX_DONE: &str = "fumika_engine_ok";

pub fn is_installed(c: &Config) -> bool {
    c.comfy_dir().map(|d| python(&d).exists() && d.join("ComfyUI").join("main.py").exists() && (cfg!(windows) || d.join(LINUX_DONE).exists()))
        .unwrap_or(false)
}

/// Version of the installed engine from ComfyUI/comfyui_version.py (`__version__ = "0.42.1"`), None when unknown.
pub fn version(c: &Config) -> Option<String> {
    let f = std::fs::read_to_string(c.comfy_dir()?.join("ComfyUI").join("comfyui_version.py")).ok()?;
    let line = f.lines().find(|l| l.trim_start().starts_with("__version__"))?;
    Some(line.split(['"', '\'']).nth(1)?.to_string())
}

/// true for "0.42" and newer (CharRef / the MOSS edit nodes need ComfyUI >= 0.42)
pub fn at_least_0_42(v: &str) -> bool {
    let n: Vec<u32> = v.split('.').map(|x| x.trim().parse().unwrap_or(0)).collect();
    (n.first().copied().unwrap_or(0), n.get(1).copied().unwrap_or(0)) >= (0, 42)
}

/// Extract the downloaded portable archive into install_dir (pure Rust 7z decoder, no external 7-Zip needed).
#[cfg(windows)]
pub fn extract(archive: &Path, install_dir: &Path) -> anyhow::Result<()> {
    std::fs::create_dir_all(install_dir)?;
    sevenz_rust2::decompress_file(archive, install_dir).map_err(|e| anyhow::anyhow!("extracting ComfyUI failed: {e}"))?;
    Ok(())
}

/// Python / PyTorch of the Linux engine = the versions the Windows portable 0.42.1 ships, so both render the same
#[cfg(unix)]
const LINUX_PYTHON: &str = "3.13";
#[cfg(unix)]
const LINUX_TORCH: [&str; 3] = ["torch==2.14.0", "torchvision==0.29.0", "torchaudio==2.11.0"];

/// Linux engine: ComfyUI source tarball -> <engine>/ComfyUI, uv -> <engine>/bin/uv, then uv puts its own Python (kept in
/// <engine>/python) and a venv with PyTorch + ComfyUI's requirements into <engine>/venv. Nothing outside install_dir is
/// touched; the wheel cache sits in downloads/uv-cache. Output goes to <install_dir>/engine_install_log.txt.
#[cfg(unix)]
pub fn install_linux(c: &Config, source: &Path, uv_archive: &Path) -> anyhow::Result<()> {
    use std::io::Write;
    use std::os::unix::fs::PermissionsExt;
    let dir = c.comfy_dir().ok_or_else(|| anyhow::anyhow!("no install folder set"))?;
    let comfy = dir.join("ComfyUI");
    let bin = dir.join("bin");
    std::fs::create_dir_all(&bin)?;
    // both tarballs have one top folder ("ComfyUI-0.42.1/", "uv-x86_64-unknown-linux-gnu/"): strip it
    let unpack = |archive: &Path, to: &Path, only: Option<&str>| -> anyhow::Result<()> {
        let mut t = tar::Archive::new(flate2::read::GzDecoder::new(std::fs::File::open(archive)?));
        for e in t.entries()? {
            let mut e = e?;
            let p = e.path()?.into_owned();
            let rel: PathBuf = p.components().skip(1).collect();
            if rel.as_os_str().is_empty() || only.is_some_and(|o| rel != Path::new(o)) {
                continue;
            }
            // a tampered archive must not write outside the engine folder: no ../ or absolute parts, no links (a link entry
            // followed by a file "through" it would land outside)
            if rel.components().any(|c| !matches!(c, std::path::Component::Normal(_))) || e.header().entry_type().is_symlink()
                || e.header().entry_type().is_hard_link() {
                anyhow::bail!("unsafe path in archive: {}", p.display());
            }
            let out = to.join(&rel);
            if let Some(d) = out.parent() {
                std::fs::create_dir_all(d)?;
            }
            e.unpack(&out)?;
        }
        Ok(())
    };
    if !comfy.join("main.py").exists() {
        unpack(source, &comfy, None).map_err(|e| anyhow::anyhow!("extracting ComfyUI failed: {e}"))?;
    }
    let uv = bin.join("uv");
    unpack(uv_archive, &bin, Some("uv")).map_err(|e| anyhow::anyhow!("extracting uv failed: {e}"))?;
    std::fs::set_permissions(&uv, std::fs::Permissions::from_mode(0o755))?;

    let log_p = c.install_dir.as_ref().unwrap().join("engine_install_log.txt");
    let mut log = std::fs::File::create(&log_p)?;
    let venv = dir.join("venv");
    let py = python(&dir).to_string_lossy().to_string();
    let reqs = comfy.join("requirements.txt").to_string_lossy().to_string();
    let mut steps: Vec<Vec<String>> = vec![];
    if !python(&dir).exists() {
        // --seed: pip inside the venv, so plugins install their packages the same way as on Windows (install_python)
        steps.push(["venv", "--seed", "--python", LINUX_PYTHON].iter().map(|s| s.to_string()).chain([venv.to_string_lossy().to_string()]).collect());
    }
    let pip = |extra: &[&str]| -> Vec<String> { ["pip", "install", "--python", &py].iter().chain(extra).map(|s| s.to_string()).collect() };
    let mut torch: Vec<&str> = LINUX_TORCH.to_vec();
    torch.extend(["--index-url", "https://download.pytorch.org/whl/cu130"]);
    steps.push(pip(&torch));
    // the pinned torch stays: the requirements list "torch" without a version. The extras are what the portable build ships
    // beyond requirements.txt (SeedVR2 imports cv2, found 22 Oct)
    steps.push(pip(&["-r", &reqs, "opencv-python-headless==5.0.0.93", "pygit2==1.20.1", "httpx==0.28.1"]));
    for s in steps {
        writeln!(log, "$ uv {}", s.join(" "))?;
        let out = Command::new(&uv).args(&s).current_dir(&dir)
            .env("UV_PYTHON_INSTALL_DIR", dir.join("python"))
            .env("UV_CACHE_DIR", c.downloads_dir().unwrap().join("uv-cache"))
            .env("UV_NO_PROGRESS", "1")
            .output()?;
        log.write_all(&out.stdout)?;
        log.write_all(&out.stderr)?;
        if !out.status.success() {
            let err = String::from_utf8_lossy(&out.stderr);
            let tail: Vec<&str> = err.lines().rev().take(4).collect();
            anyhow::bail!("setting up the engine's Python failed ({}): {}", log_p.display(), tail.into_iter().rev().collect::<Vec<_>>().join(" / "));
        }
    }
    std::fs::write(dir.join(LINUX_DONE), LINUX_TORCH.join(" "))?;
    Ok(())
}

fn copy_dir(src: &Path, dst: &Path) -> anyhow::Result<()> {
    std::fs::create_dir_all(dst)?;
    for e in std::fs::read_dir(src)? {
        let e = e?;
        let p = e.path();
        let name = e.file_name();
        if name == "__pycache__" {
            continue;
        }
        if p.is_dir() {
            copy_dir(&p, &dst.join(&name))?;
        } else {
            std::fs::copy(&p, dst.join(&name))?;
        }
    }
    Ok(())
}

/// Copy (or update) one plugin node pack into ComfyUI/custom_nodes.
pub fn install_node_pack(c: &Config, pack: &Path) -> anyhow::Result<Vec<String>> {
    let target = c.comfy_dir().ok_or_else(|| anyhow::anyhow!("no install folder set"))?.join("ComfyUI").join("custom_nodes");
    let name = pack.file_name().unwrap().to_string_lossy().to_string();
    let dst = target.join(&name);
    if dst.exists() {
        std::fs::remove_dir_all(&dst)?;
    }
    copy_dir(pack, &dst)?;
    Ok(vec![name])
}

// ---- Python packages of plugins (e.g. SeedVR2 needs diffusers / peft / omegaconf). pip runs in the engine's own Python with a
// constraints file that pins what ComfyUI depends on, so a plugin can add packages but never replace torch, numpy & co.
// A marker file remembers what is installed, so pip runs once per plugin and requirement list.

/// packages the engine relies on - pinned to their installed versions while a plugin's requirements are installed
const PINNED: [&str; 17] = ["torch", "torchvision", "torchaudio", "torchsde", "numpy", "scipy", "transformers", "tokenizers",
    "sentencepiece", "safetensors", "pillow", "opencv-python-headless", "huggingface-hub", "spandrel", "kornia", "einops",
    "comfyui-frontend-package"];

fn norm(name: &str) -> String {
    name.trim().to_lowercase().replace('_', "-")
}

/// `pip list --format=freeze` output -> constraint lines for the pinned packages ("torch==2.14.0+cu130")
pub fn constraints(freeze: &str) -> String {
    freeze.lines().filter_map(|l| {
        let (name, ver) = l.split_once("==")?;
        PINNED.contains(&norm(name).as_str()).then(|| format!("{}=={}", norm(name), ver.trim()))
    }).collect::<Vec<_>>().join("\n")
}

/// what the marker stores per plugin (order-independent)
pub fn req_key(reqs: &[String]) -> String {
    let mut r: Vec<String> = reqs.iter().map(|x| x.trim().to_string()).filter(|x| !x.is_empty()).collect();
    r.sort();
    r.join("\n")
}

fn marker(c: &Config) -> Option<PathBuf> {
    Some(c.comfy_dir()?.join("ComfyUI").join("fumika_python.json"))
}

/// true when this plugin's requirements are already installed (same list as last time)
pub fn python_done(c: &Config, plugin: &str, reqs: &[String]) -> bool {
    let m: serde_json::Value = marker(c).and_then(|p| std::fs::read_to_string(p).ok()).and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default();
    reqs.is_empty() || m.get(plugin).and_then(|v| v.as_str()) == Some(req_key(reqs).as_str())
}

/// Install a plugin's pip requirements into the engine (blocking; minutes for big packages). The pip output goes to
/// ComfyUI/fumika_pip_log.txt. Returns false when nothing had to be done.
pub fn install_python(c: &Config, plugin: &str, reqs: &[String]) -> anyhow::Result<bool> {
    if python_done(c, plugin, reqs) {
        return Ok(false);
    }
    let dir = c.comfy_dir().ok_or_else(|| anyhow::anyhow!("no install folder set"))?;
    let py = python(&dir);
    let run = |args: &[&str], log: &Path| -> anyhow::Result<std::process::Output> {
        let mut cmd = Command::new(&py);
        cmd.current_dir(&dir).arg("-s").arg("-m").arg("pip").args(args).env("PYTHONIOENCODING", "utf-8");
        #[cfg(windows)]
        cmd.creation_flags(crate::system::NO_WINDOW);
        let out = cmd.output()?;
        let mut f = std::fs::OpenOptions::new().create(true).append(true).open(log)?;
        use std::io::Write;
        writeln!(f, "$ pip {}\n{}{}", args.join(" "), String::from_utf8_lossy(&out.stdout), String::from_utf8_lossy(&out.stderr))?;
        Ok(out)
    };
    let log = dir.join("ComfyUI").join("fumika_pip_log.txt");
    // `pip list --format=freeze`, not `pip freeze`: the portable build lists its wheels as "torch @ file:///..." in pip freeze
    let freeze = run(&["list", "--format=freeze", "--disable-pip-version-check"], &log)?;
    let cons = dir.join("ComfyUI").join("fumika_constraints.txt");
    std::fs::write(&cons, constraints(&String::from_utf8_lossy(&freeze.stdout)))?;
    let cons_s = cons.to_string_lossy().to_string();
    let mut args = vec!["install", "--disable-pip-version-check", "--no-warn-script-location", "-c", cons_s.as_str()];
    args.extend(reqs.iter().map(|s| s.as_str()));
    let out = run(&args, &log)?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        let tail: Vec<&str> = err.lines().rev().take(6).collect();
        anyhow::bail!("installing the Python packages of {plugin} failed ({}): {}", log.display(),
            tail.into_iter().rev().collect::<Vec<_>>().join(" / "));
    }
    let p = marker(c).unwrap();
    let mut m: serde_json::Value = std::fs::read_to_string(&p).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(serde_json::json!({}));
    m[plugin] = serde_json::Value::String(req_key(reqs));
    std::fs::write(&p, serde_json::to_string_pretty(&m)?)?;
    Ok(true)
}

/// A file in ComfyUI/output by its /view name (subfolder + filename). Rejects anything that would leave the output folder.
pub fn output_file(c: &Config, subfolder: &str, filename: &str) -> anyhow::Result<PathBuf> {
    const SEP: [char; 2] = ['/', '\\'];
    let bad = |s: &str| s.split(SEP).any(|p| p == ".." || p.contains(':'));
    if bad(subfolder) || bad(filename) || filename.contains(SEP) || filename.is_empty() {
        anyhow::bail!("not an output file: {subfolder}/{filename}");
    }
    let out = c.comfy_dir().ok_or_else(|| anyhow::anyhow!("no install folder set"))?.join("ComfyUI").join("output");
    Ok(subfolder.split(SEP).filter(|p| !p.is_empty()).fold(out, |p, s| p.join(s)).join(filename))
}

/// Copy a user's reference picture into ComfyUI/input/fumika_refs (LoadImage reads from the input folder); returns the
/// name LoadImage expects ("fumika_refs/<file>").
pub fn import_reference(c: &Config, src: &Path) -> anyhow::Result<String> {
    let ext = src.extension().and_then(|x| x.to_str()).unwrap_or("").to_lowercase();
    if !["png", "jpg", "jpeg", "webp"].contains(&ext.as_str()) {
        anyhow::bail!("only .png, .jpg or .webp pictures");
    }
    let dir = c.comfy_dir().ok_or_else(|| anyhow::anyhow!("no install folder set"))?.join("ComfyUI").join("input").join("fumika_refs");
    std::fs::create_dir_all(&dir)?;
    // a short content hash in the name: two "photo.png" from different folders must not replace each other (earlier jobs and
    // history entries keep loading their own picture), and a picked file from fumika_refs is never copied onto itself
    let bytes = std::fs::read(src)?;
    let stem = src.file_stem().unwrap_or_default().to_string_lossy().to_string();
    let name = format!("{stem}_{:016x}.{ext}", fnv1a(&bytes));
    let dst = dir.join(&name);
    if !dst.exists() {
        std::fs::write(&dst, &bytes)?;
    }
    Ok(format!("fumika_refs/{name}"))
}

/// 64-bit FNV-1a: a stable content id for file names (not for security)
fn fnv1a(b: &[u8]) -> u64 {
    b.iter().fold(0xcbf2_9ce4_8422_2325u64, |h, x| (h ^ *x as u64).wrapping_mul(0x100_0000_01b3))
}

pub fn log_path(c: &Config) -> Option<PathBuf> {
    c.install_dir.as_ref().map(|d| d.join("comfyui_log.txt"))
}

/// ComfyUI runs WITHOUT `--enable-cors-header`: any value of that flag replaces ComfyUI's origin check, so a website open in
/// the user's browser could queue jobs on 127.0.0.1 with a simple POST. The UI never talks to ComfyUI directly; API calls go
/// through `request` and images through the `comfyimg` URI scheme (both from Rust, no Origin header).
/// Whether the engine process started by this app is still alive.
pub fn running(srv: &Server) -> bool {
    srv.0.lock().unwrap().as_mut().map(|ch| matches!(ch.try_wait(), Ok(None))).unwrap_or(false)
}

pub fn start(c: &Config, srv: &Server) -> anyhow::Result<()> {
    let mut g = srv.0.lock().unwrap();
    if let Some(ch) = g.as_mut() {
        if ch.try_wait()?.is_none() {
            return Ok(()); // already running
        }
    }
    let dir = c.comfy_dir().ok_or_else(|| anyhow::anyhow!("no install folder set"))?;
    let log = std::fs::File::create(log_path(c).unwrap())?;
    let mut cmd = Command::new(python(&dir));
    cmd.current_dir(&dir).args(["-s", "ComfyUI/main.py", "--listen", "127.0.0.1"]);
    // no --windows-standalone-build: it only opens ComfyUI in the browser on every start (user report 22 Oct) and turns on the
    // assets scan, neither of which Fumika wants; --disable-auto-launch in case a ComfyUI default changes
    cmd.arg("--disable-auto-launch");
    // Linux: the engine's own uv (bin/uv) on PATH, so the trainer plugins find it for their installs
    #[cfg(unix)]
    cmd.env("PATH", std::env::join_paths(std::iter::once(dir.join("bin")).chain(std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default())))?);
    cmd.arg("--port")
        .arg(c.port.to_string())
        // the log is a file, which Windows would write in cp1252: node packs that print emoji (SeedVR2) then fail to
        // import and can take the whole start down (UnicodeEncodeError, found 22 Oct)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .stdout(Stdio::from(log.try_clone()?))
        .stderr(Stdio::from(log));
    #[cfg(windows)]
    cmd.creation_flags(crate::system::NO_WINDOW);
    let ch = cmd.spawn()?;
    let _ = std::fs::write(pid_file(c).unwrap(), ch.id().to_string());
    *g = Some(ch);
    *srv.1.lock().unwrap() = None;
    Ok(())
}

/// <install_dir>/engine.pid: the engine this app started last, so an engine left over from a crashed app can be recognised
fn pid_file(c: &Config) -> Option<PathBuf> {
    c.install_dir.as_ref().map(|d| d.join("engine.pid"))
}

fn pid_alive(pid: u32) -> bool {
    #[cfg(windows)]
    {
        let mut cmd = Command::new("tasklist");
        cmd.args(["/FI", &format!("PID eq {pid}"), "/NH"]).creation_flags(crate::system::NO_WINDOW);
        cmd.output().map(|o| String::from_utf8_lossy(&o.stdout).split_whitespace().any(|w| w == pid.to_string())).unwrap_or(false)
    }
    #[cfg(unix)]
    {
        Path::new(&format!("/proc/{pid}")).exists()
    }
}

/// Take over the engine of a crashed earlier app run when its process is still alive; false = whatever answers on the port
/// is not ours (another ComfyUI or program).
pub fn adopt(c: &Config, srv: &Server) -> bool {
    let pid = pid_file(c).and_then(|p| std::fs::read_to_string(p).ok()).and_then(|s| s.trim().parse::<u32>().ok());
    match pid.filter(|p| pid_alive(*p)) {
        Some(p) => {
            *srv.1.lock().unwrap() = Some(p);
            true
        }
        None => false,
    }
}

pub fn stop(srv: &Server) {
    if let Some(mut ch) = srv.0.lock().unwrap().take() {
        let _ = ch.kill();
        let _ = ch.wait();
    }
    // an adopted engine has no Child handle: end it by its pid
    if let Some(pid) = srv.1.lock().unwrap().take() {
        let mut cmd = if cfg!(windows) { Command::new("taskkill") } else { Command::new("kill") };
        if cfg!(windows) { cmd.args(["/PID", &pid.to_string(), "/T", "/F"]); } else { cmd.args(["-9", &pid.to_string()]); }
        #[cfg(windows)]
        cmd.creation_flags(crate::system::NO_WINDOW);
        let _ = cmd.output();
    }
}

/// The ComfyUI API routes the UI may use through `request`.
const ALLOWED: [&str; 4] = ["/prompt", "/history/", "/interrupt", "/queue"];

/// Forward one API call to the local ComfyUI and return its JSON (or `null` for an empty body).
pub async fn request(port: u16, method: &str, path: &str, body: Option<serde_json::Value>) -> anyhow::Result<serde_json::Value> {
    if !ALLOWED.iter().any(|a| path == *a || (a.ends_with('/') && path.starts_with(a))) || path.contains("..") {
        anyhow::bail!("path not allowed: {path}");
    }
    let cl = reqwest::Client::new();
    let url = format!("http://127.0.0.1:{port}{path}");
    let req = match method {
        "GET" => cl.get(url),
        "POST" => cl.post(url).header("Content-Type", "application/json").body(body.unwrap_or(serde_json::json!({})).to_string()),
        _ => anyhow::bail!("method not allowed: {method}"),
    };
    let r = req.send().await?;
    let status = r.status();
    let text = r.text().await?;
    if !status.is_success() {
        anyhow::bail!("{status}: {text}");
    }
    Ok(if text.trim().is_empty() { serde_json::Value::Null } else { serde_json::from_str(&text)? })
}

/// `comfyimg` URI scheme -> GET /view on the local ComfyUI (query string passed through).
pub async fn view(port: u16, query: &str) -> anyhow::Result<(String, Vec<u8>)> {
    let r = reqwest::get(format!("http://127.0.0.1:{port}/view?{query}")).await?.error_for_status()?;
    let ct = r.headers().get("content-type").and_then(|v| v.to_str().ok()).unwrap_or("application/octet-stream").to_string();
    Ok((ct, r.bytes().await?.to_vec()))
}

pub async fn healthy(port: u16) -> bool {
    reqwest::get(format!("http://127.0.0.1:{port}/system_stats")).await.map(|r| r.status().is_success()).unwrap_or(false)
}

/// does the running engine serve its web UI (a page at /)? Headless setups answer the API only.
pub async fn has_ui(port: u16) -> bool {
    static CLIENT: std::sync::OnceLock<reqwest::Client> = std::sync::OnceLock::new();
    let c = CLIENT.get_or_init(|| reqwest::Client::builder().timeout(std::time::Duration::from_secs(2)).build().unwrap_or_default());
    match c.get(format!("http://127.0.0.1:{port}/")).send().await {
        Ok(r) => r.status().is_success() && r.headers().get("content-type").and_then(|v| v.to_str().ok()).is_some_and(|v| v.contains("text/html")),
        Err(_) => false,
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn pip_constraints_pin_the_engine_core() {
        let freeze = "Torch==2.14.0+cu130\ntorchvision==0.29.0+cu130\nnumpy==2.5.3\nopencv_python_headless==5.0.0.93\neinops==0.8.2\n\
                      some-pkg @ file:///x\nPillow==12.1.0\n";
        assert_eq!(super::constraints(freeze),
            "torch==2.14.0+cu130\ntorchvision==0.29.0+cu130\nnumpy==2.5.3\nopencv-python-headless==5.0.0.93\neinops==0.8.2\npillow==12.1.0");
        let a = super::req_key(&["peft>=0.17.0".into(), " diffusers>=0.33.1".into(), "".into()]);
        assert_eq!(a, super::req_key(&["diffusers>=0.33.1".into(), "peft>=0.17.0".into()]));
        // marker: done for the same list, not for a changed one; no requirements = nothing to do
        let dir = std::env::temp_dir().join(format!("fumika_pip_{}", uuid::Uuid::new_v4()));
        let c0 = crate::config::Config { install_dir: Some(dir.clone()), ..Default::default() };
        std::fs::create_dir_all(c0.comfy_dir().unwrap().join("ComfyUI")).unwrap();
        let c = crate::config::Config { install_dir: Some(dir.clone()), ..Default::default() };
        if let Some(m) = super::marker(&c) {
            std::fs::create_dir_all(m.parent().unwrap()).unwrap();
            std::fs::write(&m, serde_json::json!({"image-studio": a}).to_string()).unwrap();
            assert!(super::python_done(&c, "image-studio", &["peft>=0.17.0".into(), "diffusers>=0.33.1".into()]));
            assert!(!super::python_done(&c, "image-studio", &["peft>=0.18.0".into(), "diffusers>=0.33.1".into()]));
            assert!(!super::python_done(&c, "other", &["x".into()]));
        }
        assert!(super::python_done(&c, "none", &[]));
        let _ = std::fs::remove_dir_all(dir);
    }

    /// real pip run against an installed engine (cargo test install_python_real -- --ignored), FUMIKA_INSTALL_DIR = install folder
    #[test]
    #[ignore]
    fn install_python_real() {
        let dir = std::path::PathBuf::from(std::env::var("FUMIKA_INSTALL_DIR").expect("FUMIKA_INSTALL_DIR"));
        let c = crate::config::Config { install_dir: Some(dir), ..Default::default() };
        let reg = crate::plugins::discover(std::path::Path::new("resources"));
        let p = reg.get("image-studio").unwrap();
        let first = super::install_python(&c, &p.m.id, &p.m.python).unwrap();
        println!("installed: {first}");
        assert!(!super::install_python(&c, &p.m.id, &p.m.python).unwrap(), "second run must be a no-op");
    }

    /// real Linux engine setup (cargo test install_linux_real -- --ignored): FUMIKA_INSTALL_DIR with both tarballs in downloads/
    #[cfg(unix)]
    #[test]
    #[ignore]
    fn install_linux_real() {
        let dir = std::path::PathBuf::from(std::env::var("FUMIKA_INSTALL_DIR").expect("FUMIKA_INSTALL_DIR"));
        let c = crate::config::Config { install_dir: Some(dir.clone()), ..Default::default() };
        let d = dir.join("downloads");
        super::install_linux(&c, &d.join("ComfyUI-0.42.1.tar.gz"), &d.join("uv-x86_64-unknown-linux-gnu.tar.gz")).unwrap();
        assert!(super::is_installed(&c));
    }

    #[test]
    fn engine_version_compare() {
        assert!(super::at_least_0_42("0.42.1"));
        assert!(super::at_least_0_42("0.43.0"));
        assert!(super::at_least_0_42("1.0.0"));
        assert!(!super::at_least_0_42("0.41.0"));
        assert!(!super::at_least_0_42("0.9"));
    }

    #[test]
    fn output_file_stays_in_output() {
        let c = crate::config::Config { install_dir: Some(std::path::PathBuf::from("D:/F")), ..Default::default() };
        let p = super::output_file(&c, "fumika_assets/x", "a_1.png").unwrap();
        assert!(p.ends_with("ComfyUI/output/fumika_assets/x/a_1.png"));
        for (sub, f) in [("../x", "a.png"), ("x", "../a.png"), ("x", "a/b.png"), ("C:/x", "a.png"), ("x", "")] {
            assert!(super::output_file(&c, sub, f).is_err(), "{sub} {f}");
        }
    }

    #[tokio::test]
    async fn request_rejects_unlisted_paths() {
        for p in ["/upload/image", "/view?filename=x", "/history/../userdata", "/api/settings", "/free"] {
            assert!(super::request(1, "GET", p, None).await.unwrap_err().to_string().starts_with("path not allowed"), "{p}");
        }
        assert!(super::request(1, "DELETE", "/queue", None).await.unwrap_err().to_string().starts_with("method not allowed"));
    }
}
