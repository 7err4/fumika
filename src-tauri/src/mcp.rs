//! Local MCP server (Streamable HTTP, http://127.0.0.1:<mcp_port>/mcp, `Authorization: Bearer <mcp_token>`) so LM Studio,
//! Claude or another agent can drive the studio: render pages / MOSS JSON layouts through the persistent queue, poll jobs,
//! fetch the images. Tools are few and flat on purpose - local models call them more reliably.
//! Only loopback hosts are accepted (DNS-rebinding guard of rmcp) and every request needs the token.
use crate::{AppState, backend, catalog, comfy, graphs, plugins::Registry, queue::Queue};
use axum::http::{Request, StatusCode};
use axum::middleware::Next;
use axum::response::Response;
use base64::Engine;
use rmcp::handler::server::{router::tool::ToolRouter, wrapper::Parameters};
use rmcp::model::{CallToolResult, ContentBlock, ServerCapabilities, ServerConfig};
use rmcp::schemars::{self, JsonSchema};
use rmcp::transport::streamable_http_server::{StreamableHttpServerConfig, StreamableHttpService, session::local::LocalSessionManager};
use rmcp::{ServerHandler, tool, tool_handler, tool_router};
use serde::Deserialize;
use std::sync::Arc;
use tauri::{AppHandle, Manager, Runtime};

#[derive(Clone)]
pub struct Studio<R: Runtime> {
    app: AppHandle<R>,
    tool_router: ToolRouter<Self>,
}

#[derive(Deserialize, JsonSchema)]
pub struct RenderPage {
    /// project name (groups the jobs; pages are saved under doujin_studio/<project>/)
    pub project: String,
    /// page style: "Colour manga" (default), "Black & white manga" or "3D game render comic"; a free description is
    /// mapped to the closest of the three
    #[serde(default)]
    pub style: String,
    /// one character per line: "Name: full identity + outfit sentence"
    pub characters: String,
    /// the page: one line per panel, "panel description | speech bubble text"
    pub page: String,
    /// optional character / style LoRA file name (see list_loras)
    #[serde(default)]
    pub lora: String,
    /// true = 50-step quality mode (slower)
    #[serde(default)]
    pub quality: bool,
    /// optional absolute path of a picture of the main character (CharRef); needs the CharRef LoRA in Setup
    #[serde(default)]
    pub reference_image: String,
}

#[derive(Deserialize, JsonSchema)]
pub struct RenderLayout {
    /// project name (groups the jobs)
    pub project: String,
    /// plain prompt text or a MOSS JSON layout (summary + items with bbox in abs_centralized yxyx pixels for this size)
    pub prompt: String,
    /// image width in pixels, multiple of 16 (default 1024)
    pub width: Option<u32>,
    /// image height in pixels, multiple of 16 (default 1536)
    pub height: Option<u32>,
    /// optional LoRA file name (see list_loras)
    #[serde(default)]
    pub lora: String,
    /// LoRA strength (default 1.0)
    pub lora_strength: Option<f64>,
    /// true = fast 8-step preview instead of the full 50-step render
    #[serde(default)]
    pub preview: bool,
    /// fixed seed for a reproducible render (random if omitted)
    pub seed: Option<u64>,
}

#[derive(Deserialize, JsonSchema)]
pub struct JobRef {
    /// job id returned by render_page / render_layout
    pub job_id: String,
}

#[derive(Deserialize, JsonSchema)]
pub struct ImageRef {
    /// job id of a finished job
    pub job_id: String,
    /// which image of the job (0 = the main / best image)
    pub index: Option<usize>,
}

#[derive(Deserialize, JsonSchema)]
pub struct LoraUse {
    /// LoRA file name (see list_models)
    pub name: String,
    /// strength, default 1.0
    pub strength: Option<f64>,
}

#[derive(Deserialize, JsonSchema)]
pub struct RenderImage {
    /// project name (groups the jobs)
    pub project: String,
    /// architecture id from list_models: "moss", "anima" or "sdxl" (only the switched-on ones)
    pub family: String,
    /// the prompt (Anima / SDXL: Danbooru tags work best; MOSS: a sentence)
    pub prompt: String,
    /// optional negative prompt (nothing is added automatically)
    #[serde(default)]
    pub negative: String,
    /// size name from list_models (e.g. "portrait", "square", "landscape"; default: the architecture's first)
    #[serde(default)]
    pub size: String,
    /// optional model file of that architecture (see list_models); default: its installed base model
    #[serde(default)]
    pub model: String,
    /// any number of LoRAs, applied in this order
    #[serde(default)]
    pub loras: Vec<LoraUse>,
    /// image to image: job_id of a finished job whose first image is redrawn (or an absolute path of a picture)
    #[serde(default)]
    pub source: String,
    /// image to image: how much is redrawn, 0.05-1.0 (default 0.6)
    pub denoise: Option<f64>,
    /// number of images, 1-4 (default 1)
    pub count: Option<u32>,
    /// fixed seed for a reproducible render (random if omitted)
    pub seed: Option<u64>,
    /// optional recipe overrides (default: the architecture's tested recipe from list_models)
    pub steps: Option<u32>,
    pub cfg: Option<f64>,
    #[serde(default)]
    pub sampler: String,
    #[serde(default)]
    pub scheduler: String,
}

#[derive(Deserialize, JsonSchema)]
pub struct Upscale {
    /// project name (groups the jobs)
    pub project: String,
    /// job_id of a finished job (its image `index`, default 0) or an absolute path of a picture
    pub source: String,
    pub index: Option<usize>,
    /// "seedvr2" (best, needs its models) or "esrgan" (fast); default: seedvr2 when installed
    #[serde(default)]
    pub method: String,
    /// 2 or 4 (default 2)
    pub scale: Option<u32>,
}

#[derive(Deserialize, JsonSchema)]
pub struct ProjectRef {
    /// only jobs of this project (all projects if omitted)
    pub project: Option<String>,
}

/// random seed in 0 ..= 2^31-1: the MOSS Doujin page node takes no larger seed (found in the end-to-end test, 22 Oct)
fn seed() -> u64 {
    u64::from_le_bytes(uuid::Uuid::new_v4().as_bytes()[..8].try_into().unwrap()) >> 33
}

/// the page node's style presets (easy.py STYLES); agents often send a style sentence instead of a preset name
fn page_style(s: &str) -> &'static str {
    let l = s.to_lowercase();
    if l.contains("3d") || l.contains("render") {
        "3D game render comic"
    } else if l.contains("black") || l.contains("monochrome") || l.contains("b&w") || l.contains("screentone") || l.contains("greyscale") {
        "Black & white manga"
    } else {
        "Colour manga"
    }
}

fn safe(name: &str) -> String {
    let s: String = name.chars().filter(|c| c.is_alphanumeric() || " -_".contains(*c)).collect();
    if s.trim().is_empty() { "mcp".into() } else { s.trim().to_string() }
}

impl<R: Runtime> Studio<R> {
    fn cfg(&self) -> crate::config::Config {
        self.app.state::<AppState>().cfg.lock().unwrap().clone()
    }
    fn base_file(&self) -> String {
        let c = self.cfg();
        catalog::get(&self.app.state::<Registry>(), &c.base_model).map(|i| i.file).unwrap_or_default()
    }
    /// the SFT look LoRA file when it is downloaded (MCP pages use it like the app's default)
    fn sft_file(&self) -> String {
        self.installed_file("sft_look")
    }
    /// file name of a catalog model that is on disk, "" otherwise
    fn installed_file(&self, id: &str) -> String {
        let c = self.cfg();
        catalog::get(&self.app.state::<Registry>(), id)
            .filter(|i| crate::target_of(&c, i).map(|p| p.exists()).unwrap_or(false))
            .map(|i| i.file)
            .unwrap_or_default()
    }
    /// a workflow of a plugin that is switched on (the page / layout tools belong to the MOSS Doujin plugin)
    fn render(&self, plugin: &str, workflow: &str, vars: serde_json::Value) -> Result<serde_json::Value, String> {
        if !self.cfg().plugins.unwrap_or_default().iter().any(|p| p == plugin) {
            return Err(format!("the {plugin} plugin is switched off - turn it on in Setup"));
        }
        let reg = self.app.state::<Registry>();
        reg.get(plugin).ok_or("plugin not installed")?.render(workflow, &vars).map_err(|e| e.to_string())
    }
    fn queue(&self) -> tauri::State<'_, Queue> {
        self.app.state::<Queue>()
    }
    /// family_def of the switched-on model family plugins, in their match order (as families.ts)
    fn families(&self) -> Vec<serde_json::Value> {
        crate::checkpoints::families(&self.app.state::<Registry>(), &self.cfg())
    }
    /// model files of one architecture (its own + the ones no architecture claims), relative to its models folder
    fn model_files(&self, d: &serde_json::Value) -> Vec<String> {
        let Some(models) = self.cfg().models_dir() else { return vec![] };
        let fams = self.families();
        let mut files = vec![];
        walk_models(&models.join(d["ckptKind"].as_str().unwrap_or("diffusion_models")), "", &mut files);
        files.into_iter().filter(|f| matches!(family_of(&fams, f), Some(id) if id == d["id"]) || family_of(&fams, f).is_none()).collect()
    }
    /// a job's image as a FumikaLoadSource reference ("output:<subfolder>/<file>"), or an absolute picture path imported to input/
    fn source_ref(&self, src: &str, index: usize) -> Result<String, String> {
        if let Ok(Some(j)) = self.queue().get(src) {
            if j.state != "done" {
                return Err(format!("job {src} is {}, not done", j.state));
            }
            let imgs: Vec<&serde_json::Value> = j.outputs.as_object().into_iter().flat_map(|o| o.values())
                .flat_map(|v| v["images"].as_array().into_iter().flatten()).filter(|im| im["type"] == "output").collect();
            let im = imgs.get(index).ok_or(format!("job has {} image(s)", imgs.len()))?;
            let sub = im["subfolder"].as_str().unwrap_or("");
            return Ok(format!("output:{}{}", if sub.is_empty() { String::new() } else { format!("{sub}/") }, im["filename"].as_str().unwrap_or("")));
        }
        Ok(format!("input:{}", self.import_picture(src)?))
    }
    /// a picture an agent names by path, copied to input/fumika_refs. Agents are local and need the token, but a prompt-
    /// injected one must not turn this into a file reader: local absolute paths only (no UNC / device paths - opening
    /// \\host\x would send the Windows login hash to that host), at most 50 MB, and the bytes must be a PNG / JPEG / WEBP.
    fn import_picture(&self, src: &str) -> Result<String, String> {
        let bad = || Err("source must be a job_id or the absolute path of a local .png / .jpg / .webp picture".to_string());
        if src.starts_with("\\\\") || src.starts_with("//") || src.contains("\\\\?\\") {
            return bad();
        }
        let p = std::path::Path::new(src);
        let meta = match std::fs::metadata(p) { Ok(m) if p.is_absolute() && m.is_file() => m, _ => return bad() };
        if meta.len() > 50_000_000 {
            return Err("the picture is larger than 50 MB".into());
        }
        let mut head = [0u8; 12];
        use std::io::Read;
        let n = std::fs::File::open(p).and_then(|mut f| f.read(&mut head)).unwrap_or(0);
        let image = n >= 12 && (head.starts_with(b"\x89PNG") || head.starts_with(b"\xff\xd8\xff") || (&head[..4] == b"RIFF" && &head[8..12] == b"WEBP"));
        if !image {
            return bad();
        }
        comfy::import_reference(&self.cfg(), p).map_err(|e| e.to_string())
    }
}

use crate::checkpoints::family_of;

fn walk_models(dir: &std::path::Path, rel: &str, out: &mut Vec<String>) {
    for e in std::fs::read_dir(dir).into_iter().flatten().flatten() {
        let n = e.file_name().to_string_lossy().to_string();
        let r = if rel.is_empty() { n.clone() } else { format!("{rel}{}{n}", std::path::MAIN_SEPARATOR) };
        if e.path().is_dir() {
            walk_models(&e.path(), &r, out);
        } else if n.ends_with(".safetensors") || n.ends_with(".gguf") {
            out.push(r);
        }
    }
    out.sort();
}

#[tool_router(router = tool_router)]
impl<R: Runtime> Studio<R> {
    pub fn new(app: AppHandle<R>) -> Self {
        Self { app, tool_router: Self::tool_router() }
    }

    #[tool(description = "Engine status: is the image engine running, which base model is selected, how many jobs are queued / running.")]
    async fn studio_status(&self) -> Result<String, String> {
        let c = self.cfg();
        let running = comfy::healthy(c.port).await;
        let jobs = self.queue().list(None).map_err(|e| e.to_string())?;
        let n = |s: &str| jobs.iter().filter(|j| j.state == s).count();
        Ok(serde_json::json!({"engine_running": running, "base_model": self.base_file(), "queued": n("queued"), "running": n("running"),
            "done": n("done"), "failed": n("failed")}).to_string())
    }

    #[tool(description = "List the installed LoRA files (character and style LoRAs) that render_page / render_layout can use.")]
    async fn list_loras(&self) -> Result<String, String> {
        let dir = self.cfg().models_dir().ok_or("no install folder set")?.join("loras");
        // LoRAs that are catalog models (the turbo LoRA) are engine parts, not character / style LoRAs
        let helpers: Vec<String> = self.app.state::<Registry>().0.iter()
            .flat_map(|p| p.m.models.iter().filter(|m| m.dest == "loras").map(|m| m.file.clone())).collect();
        // sub-folders too (trained LoRAs land in <family>_training/<name>/, as the app lists them)
        let mut names = vec![];
        walk_models(&dir, "", &mut names);
        names.retain(|n| n.ends_with(".safetensors") && !helpers.iter().any(|h| n.rsplit(['/', '\\']).next() == Some(h.as_str())));
        Ok(serde_json::to_string(&names).unwrap())
    }

    #[tool(description = "Queue one comic page (panels + speech bubbles from a short page script). Returns a job_id; poll job_status, then get_image.")]
    async fn render_page(&self, Parameters(p): Parameters<RenderPage>) -> Result<String, String> {
        let prefix = format!("doujin_studio/{}/mcp_{}", safe(&p.project), &uuid::Uuid::new_v4().to_string()[..8]);
        let (reference, reference_lora) = if p.reference_image.is_empty() {
            (String::new(), String::new())
        } else {
            let lora = self.installed_file("charref_v2");
            if lora.is_empty() {
                return Err("reference_image needs the CharRef LoRA (add it in Fumika -> Setup -> Models)".into());
            }
            (self.import_picture(p.reference_image.trim())?, lora)
        };
        let g = self.render("moss-doujin", "page", serde_json::json!({"style": page_style(&p.style), "characters": p.characters, "page": p.page,
            "lora": p.lora, "base_model": self.base_file(), "sft_look": self.sft_file(), "quality": p.quality, "seed": seed(), "prefix": prefix,
            "reference": reference, "reference_lora": reference_lora}))?;
        let id = self.queue().add(&p.project, "mcp page", &g, 0).map_err(|e| e.to_string())?;
        Ok(serde_json::json!({"job_id": id, "state": "queued"}).to_string())
    }

    #[tool(description = "Queue one image from a plain prompt or a MOSS JSON layout prompt (best-practice full mode by default). Returns a job_id; poll job_status, then get_image.")]
    async fn render_layout(&self, Parameters(p): Parameters<RenderLayout>) -> Result<String, String> {
        let (w, h) = (p.width.unwrap_or(1024), p.height.unwrap_or(1536));
        if w % 16 != 0 || h % 16 != 0 || w < 256 || h < 256 || w * h > 2_400_000 {
            return Err("width / height must be multiples of 16, at least 256, at most about 2 megapixels".into());
        }
        let prefix = format!("doujin_studio/{}/layout_{}", safe(&p.project), &uuid::Uuid::new_v4().to_string()[..8]);
        let g = self.render("moss-doujin", "layout", serde_json::json!({"prompt": p.prompt, "width": w, "height": h,
            "base_model": self.base_file(), "lora": p.lora, "lora_strength": p.lora_strength.unwrap_or(1.0), "full": !p.preview,
            "seed": p.seed.unwrap_or_else(seed), "prefix": prefix}))?;
        let id = self.queue().add(&p.project, "mcp layout", &g, 0).map_err(|e| e.to_string())?;
        Ok(serde_json::json!({"job_id": id, "state": "queued"}).to_string())
    }

    #[tool(description = "State of a job (queued / running / done / failed / cancelled), its error and how many images it produced.")]
    async fn job_status(&self, Parameters(r): Parameters<JobRef>) -> Result<String, String> {
        let j = self.queue().get(&r.job_id).map_err(|e| e.to_string())?.ok_or("unknown job_id")?;
        Ok(serde_json::json!({"job_id": j.id, "project": j.project, "state": j.state, "error": j.error,
            "images": graphs::image_queries(&j.outputs).len()}).to_string())
    }

    #[tool(description = "List jobs with their state, optionally of one project.")]
    async fn list_jobs(&self, Parameters(r): Parameters<ProjectRef>) -> Result<String, String> {
        let jobs = self.queue().list(r.project.as_deref()).map_err(|e| e.to_string())?;
        let rows: Vec<_> = jobs.iter().map(|j| serde_json::json!({"job_id": j.id, "project": j.project, "label": j.label, "state": j.state})).collect();
        Ok(serde_json::to_string(&rows).unwrap())
    }

    #[tool(description = "Return one image of a finished job as a PNG (index 0 = the main / best image).")]
    async fn get_image(&self, Parameters(r): Parameters<ImageRef>) -> Result<CallToolResult, String> {
        let j = self.queue().get(&r.job_id).map_err(|e| e.to_string())?.ok_or("unknown job_id")?;
        if j.state != "done" {
            return Err(format!("job is {}, not done", j.state));
        }
        let qs = graphs::image_queries(&j.outputs);
        let q = qs.get(r.index.unwrap_or(0)).ok_or(format!("job has {} image(s)", qs.len()))?;
        let (ct, bytes) = comfy::view(self.cfg().port, q).await.map_err(|e| e.to_string())?;
        let b64 = base64::engine::general_purpose::STANDARD.encode(bytes);
        Ok(CallToolResult::success(vec![ContentBlock::image(b64, ct)]))
    }

    #[tool(description = "The switched-on architectures (moss / anima / sdxl) with their sizes, default recipe, model files and the LoRA files - what render_image accepts.")]
    async fn list_models(&self) -> Result<String, String> {
        let loras: serde_json::Value = serde_json::from_str(&self.list_loras().await?).unwrap_or_default();
        let fams: Vec<serde_json::Value> = self.families().iter().map(|d| serde_json::json!({
            "family": d["id"], "name": d["name"], "sizes": d["sizes"], "recipe": d["recipe"], "models": self.model_files(d)})).collect();
        Ok(serde_json::json!({"architectures": fams, "loras": loras,
            "note": "a LoRA only works with the architecture it was trained for (its name usually tells)"}).to_string())
    }

    #[tool(description = "Queue a single image with MOSS-Image, Anima or SDXL: text to image, or image to image when `source` is set. Uses the architecture's tested recipe. Returns a job_id; poll job_status, then get_image.")]
    async fn render_image(&self, Parameters(p): Parameters<RenderImage>) -> Result<String, String> {
        let fams = self.families();
        let d = fams.iter().find(|d| d["id"] == p.family.as_str()).ok_or_else(|| format!("architecture '{}' is not switched on; available: {}",
            p.family, fams.iter().filter_map(|d| d["id"].as_str()).collect::<Vec<_>>().join(", ")))?;
        if p.prompt.trim().is_empty() {
            return Err("prompt is empty".into());
        }
        // the architecture's text encoder / VAE must be on disk (checkpoint loaders bring both: te / vae are empty then)
        let models = self.cfg().models_dir().ok_or("no install folder set")?;
        for (key, folder) in [("te", "text_encoders"), ("te2", "text_encoders"), ("vae", "vae")] {
            let f = d[key].as_str().unwrap_or("");
            if !f.is_empty() && !models.join(folder).join(f).exists() {
                return Err(format!("{f} is missing for {} - download the {} models in Setup", p.family, d["name"].as_str().unwrap_or("")));
            }
        }
        let files = self.model_files(d);
        let unet = if !p.model.is_empty() {
            files.iter().find(|f| **f == p.model).cloned().ok_or(format!("model '{}' not found for {} (see list_models)", p.model, p.family))?
        } else {
            d["bases"].as_array().into_iter().flatten().filter_map(|b| b.as_str()).map(|b| self.installed_file(b)).find(|f| !f.is_empty())
                .or_else(|| files.iter().find(|f| family_of(&fams, f).as_deref() == d["id"].as_str()).cloned())
                .ok_or(format!("no {} model installed - download one in Setup", p.family))?
        };
        let sizes = d["sizes"].as_array().cloned().unwrap_or_default();
        let size = sizes.iter().find(|s| s[0] == p.size.as_str()).or(sizes.first()).ok_or("the architecture lists no sizes")?;
        let loras: Vec<serde_json::Value> = p.loras.iter().map(|l| serde_json::json!({"name": l.name, "strength": l.strength.unwrap_or(1.0)})).collect();
        let r = &d["recipe"];
        let sft = if d["sft"].as_bool().unwrap_or(false) { self.sft_file() } else { String::new() };
        let prefix = format!("fumika_images/{}/mcp_{}", safe(&p.project), &uuid::Uuid::new_v4().to_string()[..8]);
        let mut v = serde_json::json!({"loader": d["loader"], "unet": unet, "text_encoder": d["te"], "vae": d["vae"],
            "clip_type": d["clip"].as_str().filter(|c| !c.is_empty()).unwrap_or("stable_diffusion"), "latent_node": d["latent"],
            "clip_skip": d["clipSkip"], "clip_loras": d["clipLoras"], "turbo_lora": "", "loras": serde_json::to_string(&loras).unwrap(),
            "sft_look": sft, "sft_strength": 1.5, "te2": d["te2"].as_str().unwrap_or(""), "negative": p.negative.trim(), "seed": p.seed.unwrap_or_else(seed), "prefix": prefix,
            "steps": r["steps"], "cfg": r["cfg"], "sampler": r["sampler"], "scheduler": r["scheduler"],
            "slg": if d["slg"].as_bool().unwrap_or(false) { r["slg"].clone() } else { serde_json::json!("") },
            "prompt": p.prompt.trim(), "count": p.count.unwrap_or(1).clamp(1, 4)});
        if let Some(s) = p.steps { v["steps"] = serde_json::json!(s.clamp(1, 150)); }
        if let Some(c) = p.cfg { v["cfg"] = serde_json::json!(c.clamp(0.0, 30.0)); }
        if !p.sampler.is_empty() { v["sampler"] = serde_json::json!(p.sampler); }
        if !p.scheduler.is_empty() { v["scheduler"] = serde_json::json!(p.scheduler); }
        let workflow = if p.source.trim().is_empty() {
            v["width"] = size[1].clone();
            v["height"] = size[2].clone();
            "t2i"
        } else {
            v["source"] = serde_json::json!(self.source_ref(p.source.trim(), 0)?);
            v["denoise"] = serde_json::json!(p.denoise.unwrap_or(0.6).clamp(0.05, 1.0));
            "i2i"
        };
        let g = self.render("image-studio", workflow, v)?;
        let id = self.queue().add(&p.project, &format!("mcp image-{workflow}"), &g, 0).map_err(|e| e.to_string())?;
        Ok(serde_json::json!({"job_id": id, "state": "queued", "family": p.family, "model": unet}).to_string())
    }

    #[tool(description = "Queue an upscale of a finished job's image (or a picture path): SeedVR2 (best) or Real-ESRGAN (fast), 2x or 4x. Returns a job_id.")]
    async fn upscale_image(&self, Parameters(p): Parameters<Upscale>) -> Result<String, String> {
        let source = self.source_ref(p.source.trim(), p.index.unwrap_or(0))?;
        let scale = if p.scale == Some(4) { 4 } else { 2 };
        let dit = if self.installed_file("seedvr2_vae").is_empty() { String::new() } else {
            ["seedvr2_7b_sharp", "seedvr2_3b"].iter().map(|i| self.installed_file(i)).find(|f| !f.is_empty()).unwrap_or_default()
        };
        let esrgan = self.installed_file("realesrgan_x4");
        let method = match p.method.as_str() { "" => if dit.is_empty() { "esrgan" } else { "seedvr2" }, m => m };
        let prefix = format!("fumika_images/{}/mcp_up_{}", safe(&p.project), &uuid::Uuid::new_v4().to_string()[..8]);
        let (workflow, v) = match method {
            "seedvr2" if !dit.is_empty() => ("upscale_seedvr2", serde_json::json!({"source": source, "prefix": prefix, "scale": scale, "seed": seed(),
                "dit": dit, "max_resolution": 4096})),
            "esrgan" if !esrgan.is_empty() => ("upscale_esrgan", serde_json::json!({"source": source, "prefix": prefix,
                "esrgan_factor": scale as f64 / 4.0, "upscaler": esrgan})),
            "seedvr2" | "esrgan" => return Err(format!("the {method} models are not downloaded - Setup -> Image Studio")),
            m => return Err(format!("unknown method '{m}' (seedvr2 or esrgan)")),
        };
        let g = self.render("image-studio", workflow, v)?;
        let id = self.queue().add(&p.project, &format!("mcp {workflow}"), &g, 0).map_err(|e| e.to_string())?;
        Ok(serde_json::json!({"job_id": id, "state": "queued", "method": method}).to_string())
    }

    #[tool(description = "Cancel a queued or running job.")]
    async fn cancel_job(&self, Parameters(r): Parameters<JobRef>) -> Result<String, String> {
        let running = self.queue().cancel(&r.job_id).map_err(|e| e.to_string())?;
        if running {
            crate::queue::interrupt(&backend(&self.app), &r.job_id).await;
        }
        Ok("cancelled".into())
    }
}

#[tool_handler(router = self.tool_router)]
impl<R: Runtime> ServerHandler for Studio<R> {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build()).with_instructions(
            "Fumika: renders comic pages, MOSS JSON layouts and single images (MOSS-Image, Anima, SDXL - see list_models) on \
             the local GPU and upscales them. Rendering is queued: render_* / upscale_image return a job_id, poll job_status \
             every few seconds (a render takes ~5-60 s), then get_image.",
        )
    }
}

async fn require_token(token: Arc<String>, req: Request<axum::body::Body>, next: Next) -> Result<Response, StatusCode> {
    let ok = req.headers().get("authorization").and_then(|v| v.to_str().ok()).map(|v| v == format!("Bearer {token}")).unwrap_or(false);
    if ok { Ok(next.run(req).await) } else { Err(StatusCode::UNAUTHORIZED) }
}

/// Start the MCP server on 127.0.0.1:<port> (runs until the app exits).
pub fn spawn<R: Runtime>(app: AppHandle<R>, port: u16, token: String) {
    tauri::async_runtime::spawn(async move {
        let a = app.clone();
        let service = StreamableHttpService::new(move || Ok(Studio::new(a.clone())), Arc::new(LocalSessionManager::default()),
            StreamableHttpServerConfig::default());
        let token = Arc::new(token);
        let router = axum::Router::new()
            .nest_service("/mcp", service)
            .layer(axum::middleware::from_fn(move |req, next| require_token(token.clone(), req, next)));
        match tokio::net::TcpListener::bind(("127.0.0.1", port)).await {
            Ok(l) => {
                let _ = axum::serve(l, router).await;
            }
            Err(e) => eprintln!("MCP server could not bind 127.0.0.1:{port}: {e}"),
        }
    });
}


#[cfg(test)]
mod tests {
    #[test]
    fn page_styles_and_seeds() {
        assert_eq!(super::page_style("Colour manga"), "Colour manga");
        assert_eq!(super::page_style("Full color anime manga page, clean lineart, cel shading"), "Colour manga");
        assert_eq!(super::page_style("Black & white manga"), "Black & white manga");
        assert_eq!(super::page_style("monochrome ink, screentones"), "Black & white manga");
        assert_eq!(super::page_style("3D game render comic"), "3D game render comic");
        assert_eq!(super::page_style(""), "Colour manga");
        assert!((0..200).all(|_| super::seed() <= 2_147_483_647));
    }

    #[test]
    fn model_files_find_their_architecture() {
        // the real family_defs, in the order the app uses (sdxl before anima: "animagine" contains "anima")
        let reg = crate::plugins::discover(std::path::Path::new("resources"));
        let mut fams: Vec<serde_json::Value> = reg.0.iter().filter_map(|p| p.m.family_def.clone()).collect();
        fams.sort_by(|a, b| a["order"].as_f64().unwrap_or(99.0).total_cmp(&b["order"].as_f64().unwrap_or(99.0)));
        let f = |n: &str| super::family_of(&fams, n);
        assert_eq!(f("moss_image_base_bf16.safetensors").as_deref(), Some("moss"));
        assert_eq!(f("anima-base-v1.0.safetensors").as_deref(), Some("anima"));
        assert_eq!(f("animagine-xl-4.0.safetensors").as_deref(), Some("sdxl"));
        assert_eq!(f("sub/Illustrious-XL-v2.0.safetensors").as_deref(), Some("sdxl"));
        assert_eq!(f("myMix_v3.safetensors"), None);
        // Anima 3.8B v1.1 has its own family (loader + 2nd encoder); 3.8B v1 and 2.9B are plain Anima
        assert_eq!(f("anima-3.8b/Anima-3.8B-v1.1.safetensors").as_deref(), Some("anima38"));
        assert_eq!(f("animaExpanded38B_10.safetensors").as_deref(), Some("anima"));
        // lylogummy's 3.8B v1 (official HF name) is plain Anima too; only v1.1 / v2 bundles need the Qwen3.5 family
        assert_eq!(f("Anima-3.8B.safetensors").as_deref(), Some("anima"));
        assert_eq!(f("Anima-3.8B-v2.safetensors").as_deref(), Some("anima38"));
        assert_eq!(f("Anima-2.9B-preview-v1.safetensors").as_deref(), Some("anima"));
    }
}
