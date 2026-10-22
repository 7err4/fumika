//! A1111-style generation parameters ("parameters" text chunk) from a job's ComfyUI graph: the format A1111, Forge and Civitai
//! read - Civitai fills in the generation data and links the models and LoRAs by their AutoV2 hashes (first 10 hex digits of
//! the file's SHA256). ComfyUI's own "prompt" chunk (the whole graph) stays as it is; ComfyUI opens a picture from it.
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use crate::config::Config;

/// the graph node an input points to (["8", 0] -> node "8")
fn linked<'a>(g: &'a Value, v: &Value) -> Option<&'a Value> {
    v.as_array().and_then(|a| a.first()).and_then(|id| id.as_str()).and_then(|id| g.get(id))
}

/// the text a conditioning comes from: a "text" / "prompt" string, followed through links (FumikaPromptEncode, asset sheets)
fn text_of(g: &Value, n: &Value, depth: u8) -> String {
    if depth > 4 {
        return String::new();
    }
    let i = &n["inputs"];
    for k in ["text", "prompt"] {
        if let Some(s) = i[k].as_str() {
            return s.trim().to_string();
        }
        if let Some(m) = linked(g, &i[k]) {
            return text_of(g, m, depth + 1);
        }
    }
    // a node that builds the prompt from parts (Asset Studio sheet): its descriptive string inputs
    ["style", "character", "asset", "page"].iter().filter_map(|k| i[*k].as_str()).map(str::trim).filter(|s| !s.is_empty())
        .collect::<Vec<_>>().join(", ")
}

fn base(f: &str) -> &str {
    let n = f.rsplit(['/', '\\']).next().unwrap_or(f);
    n.strip_suffix(".safetensors").or_else(|| n.strip_suffix(".gguf")).or_else(|| n.strip_suffix(".ckpt")).unwrap_or(n)
}

/// the LoRAs a graph applies: LoraLoader nodes, Fumika LoRA stacks ("loras" JSON) and the doujin page's named LoRA inputs
fn loras(g: &Value) -> Vec<(String, f64)> {
    let mut out: Vec<(String, f64)> = vec![];
    let mut add = |name: &str, w: f64| {
        let name = name.trim();
        // "none" / "auto" / "auto (find it by name)" are the nodes' placeholders, not files ("autumn_style.safetensors" is one)
        let placeholder = name == "none" || name == "auto" || name.starts_with("auto (");
        if !name.is_empty() && !placeholder && w != 0.0 && !out.iter().any(|(n, _)| n == name) {
            out.push((name.to_string(), w));
        }
    };
    for n in g.as_object().into_iter().flat_map(|o| o.values()) {
        let i = &n["inputs"];
        if let Some(l) = i["lora_name"].as_str() {
            add(l, i["strength_model"].as_f64().unwrap_or(1.0));
        }
        if let Some(js) = i["loras"].as_str() {
            for l in serde_json::from_str::<Vec<Value>>(js).unwrap_or_default() {
                if let Some(name) = l["name"].as_str().or_else(|| l["lora"].as_str()) {
                    add(name, l["strength"].as_f64().unwrap_or(1.0));
                }
            }
        }
        for (k, s) in [("character_lora", "lora_strength"), ("lora_2", "lora_2_strength"), ("reference_lora", "reference_strength")] {
            if let Some(l) = i[k].as_str() {
                add(l, i[s].as_f64().unwrap_or(1.0));
            }
        }
    }
    out
}

/// the main model file: a loader's unet / checkpoint name, or the doujin page's base model. Key order first, then nodes:
/// a generic "model_name" (an upscale model loader, say) never beats a unet / checkpoint loader elsewhere in the graph
fn model(g: &Value) -> Option<String> {
    let nodes = g.as_object()?;
    ["unet_name", "ckpt_name", "unet", "base_model", "model_name"].iter().find_map(|k| {
        nodes.values().filter_map(|n| n["inputs"][*k].as_str())
            .find(|s| s.ends_with(".safetensors") || s.ends_with(".gguf") || s.ends_with(".ckpt")).map(String::from)
    })
}

static CACHE: Mutex<Option<HashMap<String, (u64, u64, String)>>> = Mutex::new(None);

fn cache_path() -> PathBuf {
    crate::config::app_dir().join("model_hashes.json")
}

/// AutoV2 hash of a model file, cached by path + size + modification time (a 20 GB checkpoint takes seconds once)
pub fn autov2(p: &Path) -> Option<String> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let meta = std::fs::metadata(p).ok()?;
    let mtime = meta.modified().ok()?.duration_since(std::time::UNIX_EPOCH).ok()?.as_secs();
    let key = p.to_string_lossy().to_string();
    {
        let mut guard = CACHE.lock().unwrap();
        let cache = guard.get_or_insert_with(|| std::fs::read(cache_path()).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default());
        if let Some((s, t, h)) = cache.get(&key) {
            if *s == meta.len() && *t == mtime {
                return Some(h.clone());
            }
        }
    }
    // hash without holding the cache: a first multi-GB checkpoint must not hold up other lookups
    let mut f = std::fs::File::open(p).ok()?;
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; 8 << 20];
    loop {
        let n = f.read(&mut buf).ok()?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    let h = format!("{:x}", hasher.finalize())[..10].to_string();
    let mut guard = CACHE.lock().unwrap();
    let cache = guard.get_or_insert_with(Default::default);
    cache.insert(key, (meta.len(), mtime, h.clone()));
    let _ = std::fs::write(cache_path(), serde_json::to_vec(cache).unwrap_or_default());
    Some(h)
}

/// a model name from the graph -> its file in the engine's model folders
fn find(c: &Config, name: &str, kinds: &[&str]) -> Option<PathBuf> {
    let m = c.models_dir()?;
    kinds.iter().map(|k| m.join(k).join(name)).find(|p| p.is_file())
}

/// what the doujin page node's "auto" settings mean (moss-doujin expert.sampling): quality = 50 steps cfg 3 euler / sgm_uniform with
/// the stray-bubble negative, fast = 8 steps cfg 1 euler / simple; "auto" speed draws title pages (a `# title` bubble) in quality.
/// A1111 readers (Civitai) need the "Steps:" line, so the page must name them.
fn doujin_auto(i: &Value) -> (f64, f64, String, String, String) {
    let speed = i["speed"].as_str().unwrap_or("auto");
    let title = i["page"].as_str().unwrap_or("").lines().flat_map(|l| l.split('|').skip(1))
        .any(|b| b.trim().starts_with('#') && !b.trim().starts_with("##"));
    let slow = speed.starts_with("quality") || (speed.starts_with("auto") && title)
        || i["turbo_lora"].as_str().is_some_and(|t| t.starts_with("none"));
    let set = |k: &str| i[k].as_str().filter(|v| !v.is_empty() && *v != "auto").map(String::from);
    let num = |k: &str, d: f64| i[k].as_f64().filter(|v| *v > 0.0).unwrap_or(d);
    let neg = match i["negative"].as_str().unwrap_or("auto") {
        "auto" => if slow { "extra speech bubbles, gibberish text, watermark".to_string() } else { String::new() },
        n if n.trim().eq_ignore_ascii_case("off") => String::new(),
        n => n.to_string(),
    };
    (num("steps", if slow { 50.0 } else { 8.0 }), num("cfg", if slow { 3.0 } else { 1.0 }), set("sampler").unwrap_or("euler".into()),
     set("scheduler").unwrap_or(if slow { "sgm_uniform" } else { "simple" }.into()), neg)
}

/// the "parameters" text for one picture of the job (A1111 layout); None when the graph has nothing to describe
pub fn parameters(c: Option<&Config>, g: &Value, width: u32, height: u32) -> Option<String> {
    let nodes = g.as_object()?;
    // the main pass: with a second (hires / refine) sampler in the graph, the one with the highest denoise
    let den = |n: &Value| n["inputs"]["denoise"].as_f64().unwrap_or(1.0);
    let sampler = nodes.values().filter(|n| n["class_type"].as_str().is_some_and(|t| t.contains("KSampler")))
        .fold(None::<&Value>, |best, n| if best.is_some_and(|b| den(b) >= den(n)) { best } else { Some(n) });
    // a sampler node; else the node that samples itself (the doujin page): steps / cfg / seed among its inputs
    let s = sampler.or_else(|| nodes.values().find(|n| n["inputs"].get("seed").is_some() || n["inputs"].get("noise_seed").is_some()))?;
    let i = &s["inputs"];
    let page = (sampler.is_none() && i.get("page").is_some()).then(|| doujin_auto(i));
    let (pos, neg) = match sampler {
        Some(k) => (linked(g, &k["inputs"]["positive"]).map(|n| text_of(g, n, 0)).unwrap_or_default(),
                    linked(g, &k["inputs"]["negative"]).map(|n| text_of(g, n, 0)).unwrap_or_default()),
        None => {
            // the doujin page: style + page text is what it draws
            let p = ["style", "page"].iter().filter_map(|k| i[*k].as_str()).map(str::trim).filter(|x| !x.is_empty()).collect::<Vec<_>>().join("\n");
            (p, page.as_ref().map(|a| a.4.clone()).unwrap_or_default())
        }
    };
    let ls = loras(g);
    let mut prompt = pos;
    for (n, w) in &ls {
        prompt.push_str(&format!(" <lora:{}:{}>", base(n), w));
    }
    let mut out = prompt.trim().to_string();
    if !neg.is_empty() {
        out.push_str(&format!("\nNegative prompt: {neg}"));
    }
    let mut kv: Vec<String> = vec![];
    let num = |k: &str| i[k].as_f64().filter(|v| *v > 0.0);
    let word = |k: &str| i[k].as_str().filter(|v| !v.is_empty() && *v != "auto").map(String::from);
    if let Some((steps, cfg, sa, sc, _)) = &page {
        kv.extend([format!("Steps: {steps}"), format!("Sampler: {sa}"), format!("Schedule type: {sc}"), format!("CFG scale: {cfg}")]);
    } else {
        if let Some(v) = num("steps") { kv.push(format!("Steps: {v}")); }
        if let Some(v) = word("sampler_name").or_else(|| word("sampler")) { kv.push(format!("Sampler: {v}")); }
        if let Some(v) = word("scheduler") { kv.push(format!("Schedule type: {v}")); }
        if let Some(v) = num("cfg") { kv.push(format!("CFG scale: {v}")); }
    }
    // KSamplerAdvanced names it noise_seed
    if let Some(v) = i["seed"].as_u64().or_else(|| i["noise_seed"].as_u64()) { kv.push(format!("Seed: {v}")); }
    kv.push(format!("Size: {width}x{height}"));
    if let Some(m) = model(g) {
        if let Some(h) = c.and_then(|c| find(c, &m, &["diffusion_models", "checkpoints", "unet"])).and_then(|p| autov2(&p)) {
            kv.push(format!("Model hash: {h}"));
        }
        kv.push(format!("Model: {}", base(&m)));
    }
    if let Some(d) = i["denoise"].as_f64().filter(|d| *d < 1.0) {
        kv.push(format!("Denoising strength: {d}"));
    }
    let hashes: Vec<String> = ls.iter().filter_map(|(n, _)| {
        c.and_then(|c| find(c, n, &["loras"])).and_then(|p| autov2(&p)).map(|h| format!("{}: {h}", base(n)))
    }).collect();
    if !hashes.is_empty() {
        kv.push(format!("Lora hashes: \"{}\"", hashes.join(", ")));
    }
    kv.push(format!("Version: Fumika {}", env!("CARGO_PKG_VERSION")));
    out.push('\n');
    out.push_str(&kv.join(", "));
    Some(out)
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    #[test]
    fn image_studio_graph_becomes_a1111_parameters() {
        let g = json!({
            "1": {"class_type": "FumikaModelLoader", "inputs": {"unet": "anima-base-v1.0.safetensors"}},
            "5": {"class_type": "FumikaLoraStack", "inputs": {"model": ["1", 0], "loras": "[{\"name\": \"terra\\\\terra_v1.safetensors\", \"strength\": 0.8}]"}},
            "8": {"class_type": "FumikaPromptEncode", "inputs": {"text": "terra7err4, 1girl, cafe"}},
            "9": {"class_type": "CLIPTextEncode", "inputs": {"text": "worst quality"}},
            "11": {"class_type": "KSampler", "inputs": {"positive": ["8", 0], "negative": ["9", 0], "seed": 7, "steps": 30, "cfg": 4.5,
                   "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1.0}},
        });
        let p = super::parameters(None, &g, 832, 1216).unwrap();
        assert!(p.starts_with("terra7err4, 1girl, cafe <lora:terra_v1:0.8>\nNegative prompt: worst quality\n"), "{p}");
        assert!(p.contains("Steps: 30, Sampler: er_sde, Schedule type: simple, CFG scale: 4.5, Seed: 7, Size: 832x1216"), "{p}");
        assert!(p.contains("Model: anima-base-v1.0") && p.ends_with(&format!("Version: Fumika {}", env!("CARGO_PKG_VERSION"))), "{p}");
        assert!(!p.contains("Denoising"));
    }

    #[test]
    fn main_sampler_model_and_lora_names() {
        let g = json!({
            "1": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x_upscale.safetensors"}},
            "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-base-v1.0.safetensors"}},
            "3": {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": "autumn_style.safetensors", "strength_model": 0.7}},
            "4": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 9, "steps": 20, "cfg": 4.0}},
            "5": {"class_type": "KSampler", "inputs": {"seed": 3, "steps": 8, "cfg": 4.0, "denoise": 0.4}},
        });
        let p = super::parameters(None, &g, 64, 64).unwrap();
        assert!(p.contains("<lora:autumn_style:0.7>") && p.contains("Model: anima-base-v1.0") && p.contains("Seed: 9, "), "{p}");
        assert!(p.contains("Steps: 20") && !p.contains("Denoising"), "{p}");
    }

    #[test]
    fn doujin_page_describes_style_and_page() {
        let g = json!({"1": {"class_type": "MossEasyDoujinPage", "inputs": {"style": "Colour manga", "page": "Fumika inks | Done!",
            "seed": 42, "steps": 0, "cfg": 0, "sampler": "auto", "negative": "auto", "base_model": "moss_image_base_bf16.safetensors",
            "lora_2": "moss_image_sft_look_lora.safetensors", "lora_2_strength": 1.5, "character_lora": "none"}}});
        let p = super::parameters(None, &g, 1024, 1536).unwrap();
        // a normal page is drawn fast (8 steps, no negative); Civitai only reads the text when the settings line starts with "Steps: "
        assert!(p.starts_with("Colour manga\nFumika inks | Done! <lora:moss_image_sft_look_lora:1.5>\nSteps: 8, Sampler: euler, \
            Schedule type: simple, CFG scale: 1, Seed: 42, Size: 1024x1536"), "{p}");
        assert!(!p.contains("Negative prompt") && p.contains("Model: moss_image_base_bf16"), "{p}");
        // a title page in auto speed: the quality recipe with its negative; expert values win
        let mut t = g.clone();
        t["1"]["inputs"]["page"] = json!("Fumika on the cover | #DEADLINE! | ##by Fumika");
        let p = super::parameters(None, &t, 1024, 1536).unwrap();
        assert!(p.contains("\nNegative prompt: extra speech bubbles, gibberish text, watermark\nSteps: 50, Sampler: euler, \
            Schedule type: sgm_uniform, CFG scale: 3,"), "{p}");
        t["1"]["inputs"]["steps"] = json!(30);
        assert!(super::parameters(None, &t, 1024, 1536).unwrap().contains("Steps: 30, "));
    }
}

#[cfg(test)]
mod real_png {
    #[test]
    #[ignore]
    fn parameters_of_a_real_comfyui_png() {
        let png = std::fs::read(std::env::var("PNG").unwrap()).unwrap();
        let mut i = 8;
        let mut graph = None;
        while i + 12 <= png.len() {
            let len = u32::from_be_bytes(png[i..i + 4].try_into().unwrap()) as usize;
            let d = &png[i + 8..i + 8 + len];
            if &png[i + 4..i + 8] == b"tEXt" && d.starts_with(b"prompt\0") {
                graph = serde_json::from_slice::<serde_json::Value>(&d[7..]).ok();
            }
            i += 12 + len;
        }
        let (w, h) = crate::aimark::png_size(&png).unwrap();
        println!("{}", super::parameters(None, &graph.unwrap(), w, h).unwrap());
    }
}
