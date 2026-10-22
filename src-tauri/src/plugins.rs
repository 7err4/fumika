//! Plugins: everything model-specific lives in `plugins/<id>/plugin.json` - the models to download, the ComfyUI node packs and
//! the workflow templates. Bundled plugins come with the app (resources/plugins), user plugins live in %APPDATA%/Fumika/plugins
//! (same id = the user copy wins). The core (queue, ComfyUI, downloads, projects, MCP) knows no model.
//!
//! Workflow templates are ComfyUI API graphs with placeholders:
//!   "{{name}}"                  the variable (typed: numbers stay numbers)
//!   "{{name ?? \"none\"}}"      a fallback when the variable is missing, null or ""
//!   "{{full ? 50 : 8}}"         a choice on a truthy variable (values are JSON literals)
//!   "text {{name}} text"        inside a longer string: string interpolation
//!   node "_when": "lora"        the node is dropped when the variable is falsy; references to it are rewired to its
//!   node "_bypass": "model"     input `model` (so an optional LoRA / guidance node can sit in the middle of a chain)
//!   node "_unlink": true        ... or the inputs that use it are removed (an optional input such as a reference picture)
use crate::catalog::Item;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Workflow {
    pub file: String,
    #[serde(default)]
    pub defaults: Map<String, Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Manifest {
    pub id: String,
    pub name: String,
    pub version: String,
    #[serde(default)]
    pub author: String,
    pub description: String,
    /// "generate" | "train" | "tool"
    pub kinds: Vec<String>,
    /// model family, e.g. "MOSS-Image", "Anima"
    pub family: String,
    /// "sfw" | "nsfw" - NSFW plugins are never bundled, users install them themselves
    pub content: String,
    /// licence of the plugin's own files (node packs)
    pub license: String,
    /// app areas the plugin brings: "comic" (projects, reader, templates), "trainer"
    #[serde(default)]
    pub ui: Vec<String>,
    /// node pack folders relative to the plugin folder, copied into ComfyUI/custom_nodes
    #[serde(default)]
    pub nodes: Vec<String>,
    /// pip requirements of the node packs that the engine does not ship (installed with the engine's core packages pinned)
    #[serde(default)]
    pub python: Vec<String>,
    /// model family plugins (kind "family"): loaders, tested recipe, options and presets of the architecture (read by the app)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub family_def: Option<Value>,
    /// plugins switched on together with this one (e.g. a workspace needs its model family)
    #[serde(default)]
    pub requires: Vec<String>,
    /// at least one of these is switched on with it (the Image Studio works with any model family)
    #[serde(default)]
    pub requires_one: Vec<String>,
    #[serde(default)]
    pub models: Vec<Item>,
    #[serde(default)]
    pub workflows: BTreeMap<String, Workflow>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Plugin {
    #[serde(flatten)]
    pub m: Manifest,
    #[serde(skip)]
    pub dir: PathBuf,
    pub bundled: bool,
}

/// managed Tauri state: all plugins found at start
pub struct Registry(pub Vec<Plugin>);

impl Registry {
    pub fn get(&self, id: &str) -> Option<&Plugin> {
        self.0.iter().find(|p| p.m.id == id)
    }
    /// plugins switched on in the config (None = the user has not chosen yet)
    /// the chosen plugins plus what they need: every `requires`, and the first of `requires_one` when none of them is chosen
    pub fn with_requirements(&self, ids: &[String]) -> Vec<String> {
        let mut out: Vec<String> = ids.to_vec();
        let mut i = 0;
        while i < out.len() {
            if let Some(p) = self.get(&out[i]) {
                let mut add: Vec<String> = p.m.requires.clone();
                if !p.m.requires_one.is_empty() && !p.m.requires_one.iter().any(|r| out.contains(r)) {
                    add.push(p.m.requires_one[0].clone());
                }
                for a in add {
                    if !out.contains(&a) && self.get(&a).is_some() {
                        out.push(a);
                    }
                }
            }
            i += 1;
        }
        out
    }

    pub fn enabled<'a>(&'a self, ids: &Option<Vec<String>>) -> Vec<&'a Plugin> {
        match ids {
            Some(ids) => self.0.iter().filter(|p| ids.contains(&p.m.id)).collect(),
            None => vec![],
        }
    }
}

pub fn user_dir() -> PathBuf {
    crate::config::app_dir().join("plugins")
}

fn read_dir(dir: &Path, bundled: bool, out: &mut Vec<Plugin>) {
    let Ok(rd) = std::fs::read_dir(dir) else { return };
    for e in rd.flatten() {
        let f = e.path().join("plugin.json");
        let Ok(s) = std::fs::read_to_string(&f) else { continue };
        match serde_json::from_str::<Manifest>(&s) {
            Ok(m) => {
                out.retain(|p: &Plugin| p.m.id != m.id); // a user copy replaces the bundled one
                out.push(Plugin { m, dir: e.path(), bundled });
            }
            Err(err) => eprintln!("[plugins] skipping {}: {err}", f.display()),
        }
    }
}

pub fn discover(resource_dir: &Path) -> Registry {
    let mut out = vec![];
    read_dir(&resource_dir.join("plugins"), true, &mut out);
    read_dir(&user_dir(), false, &mut out);
    out.sort_by(|a, b| a.m.name.cmp(&b.m.name));
    Registry(out)
}

impl Plugin {
    pub fn node_dirs(&self) -> Vec<PathBuf> {
        self.m.nodes.iter().map(|n| self.dir.join(n)).filter(|p| p.is_dir()).collect()
    }

    /// ComfyUI API graph of one of the plugin's workflows, with `vars` over the workflow defaults
    pub fn render(&self, workflow: &str, vars: &Value) -> anyhow::Result<Value> {
        let w = self.m.workflows.get(workflow).ok_or_else(|| anyhow::anyhow!("plugin {} has no workflow '{workflow}'", self.m.id))?;
        let template: Value = serde_json::from_str(&std::fs::read_to_string(self.dir.join(&w.file))?)?;
        let mut all = w.defaults.clone();
        if let Some(o) = vars.as_object() {
            all.extend(o.clone());
        }
        fill_graph(&template, &all)
    }
}

fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().unwrap_or(0.0) != 0.0,
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// position of `pat` outside of "..." string literals
fn find_top(s: &str, pat: &str) -> Option<usize> {
    let (mut quoted, mut esc) = (false, false);
    for (i, c) in s.char_indices() {
        if quoted {
            if esc {
                esc = false;
            } else if c == '\\' {
                esc = true;
            } else if c == '"' {
                quoted = false;
            }
        } else if c == '"' {
            quoted = true;
        } else if s[i..].starts_with(pat) {
            return Some(i);
        }
    }
    None
}

fn literal(s: &str) -> anyhow::Result<Value> {
    serde_json::from_str(s.trim()).map_err(|e| anyhow::anyhow!("bad literal `{}` in a template: {e}", s.trim()))
}

fn var<'a>(vars: &'a Map<String, Value>, name: &str) -> anyhow::Result<&'a Value> {
    vars.get(name).ok_or_else(|| anyhow::anyhow!("template variable '{name}' is missing"))
}

/// one {{...}} expression
fn eval(expr: &str, vars: &Map<String, Value>) -> anyhow::Result<Value> {
    let e = expr.trim();
    if let Some(i) = find_top(e, "??") {
        let v = vars.get(e[..i].trim());
        return if truthy(v) || matches!(v, Some(Value::Bool(_)) | Some(Value::Number(_))) { Ok(v.unwrap().clone()) } else { literal(&e[i + 2..]) };
    }
    if let Some(q) = find_top(e, "?") {
        let rest = &e[q + 1..];
        let c = find_top(rest, ":").ok_or_else(|| anyhow::anyhow!("`{e}`: a ? needs a :"))?;
        return literal(if truthy(vars.get(e[..q].trim())) { &rest[..c] } else { &rest[c + 1..] });
    }
    Ok(var(vars, e)?.clone())
}

fn fill_str(s: &str, vars: &Map<String, Value>) -> anyhow::Result<Value> {
    // the whole string is one placeholder -> keep the value's type
    if s.starts_with("{{") && s.ends_with("}}") && s.matches("{{").count() == 1 {
        return eval(&s[2..s.len() - 2], vars);
    }
    let (mut out, mut rest) = (String::new(), s);
    while let Some(a) = rest.find("{{") {
        let b = rest[a..].find("}}").ok_or_else(|| anyhow::anyhow!("unclosed {{{{ in `{s}`"))? + a;
        out.push_str(&rest[..a]);
        match eval(&rest[a + 2..b], vars)? {
            Value::String(v) => out.push_str(&v),
            v => out.push_str(&v.to_string()),
        }
        rest = &rest[b + 2..];
    }
    out.push_str(rest);
    Ok(Value::String(out))
}

fn fill(v: &Value, vars: &Map<String, Value>) -> anyhow::Result<Value> {
    Ok(match v {
        Value::String(s) => fill_str(s, vars)?,
        Value::Array(a) => Value::Array(a.iter().map(|x| fill(x, vars)).collect::<anyhow::Result<_>>()?),
        Value::Object(o) => Value::Object(o.iter().map(|(k, x)| Ok((k.clone(), fill(x, vars)?))).collect::<anyhow::Result<_>>()?),
        x => x.clone(),
    })
}

/// replace every link ["<id>", n] in `v` by `to`
fn rewire(v: &mut Value, id: &str, to: &Value) {
    match v {
        Value::Array(a) if a.len() == 2 && a[0].as_str() == Some(id) && a[1].is_number() => *v = to.clone(),
        Value::Array(a) => a.iter_mut().for_each(|x| rewire(x, id, to)),
        Value::Object(o) => o.values_mut().for_each(|x| rewire(x, id, to)),
        _ => {}
    }
}

pub fn fill_graph(template: &Value, vars: &Map<String, Value>) -> anyhow::Result<Value> {
    let nodes = template.as_object().ok_or_else(|| anyhow::anyhow!("a workflow template must be an object of nodes"))?;
    let mut g = Map::new();
    let mut drop = vec![];
    for (id, node) in nodes {
        let mut n = fill(node, vars)?;
        let o = n.as_object_mut().ok_or_else(|| anyhow::anyhow!("node {id} is not an object"))?;
        let when = o.remove("_when");
        let bypass = o.remove("_bypass");
        let unlink = o.remove("_unlink").map(|u| u == Value::Bool(true)).unwrap_or(false);
        if let Some(w) = when.as_ref().and_then(|w| w.as_str()) {
            let keep = match w.strip_prefix('!') {
                Some(name) => !truthy(vars.get(name.trim())),
                None => truthy(vars.get(w.trim())),
            };
            if !keep {
                drop.push((id.clone(), bypass.and_then(|b| b.as_str().map(String::from)), unlink));
            }
        }
        g.insert(id.clone(), n);
    }
    for (id, bypass, unlink) in drop {
        let node = g.remove(&id).unwrap();
        let to = bypass.and_then(|b| node["inputs"].get(&b).cloned());
        match to {
            Some(to) => g.values_mut().for_each(|n| rewire(n, &id, &to)),
            None if unlink => g.values_mut().for_each(|n| {
                if let Some(inp) = n.get_mut("inputs").and_then(|i| i.as_object_mut()) {
                    inp.retain(|_, v| !(v.as_array().map(|a| a.len() == 2 && a[0].as_str() == Some(id.as_str())).unwrap_or(false)));
                }
            }),
            None => {
                if serde_json::to_string(&g)?.contains(&format!("[\"{id}\",")) {
                    anyhow::bail!("node {id} was dropped by _when but is still used and has no _bypass");
                }
            }
        }
    }
    Ok(Value::Object(g))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn moss(file: &str) -> Value {
        serde_json::from_str(&std::fs::read_to_string(format!("resources/plugins/moss-doujin/workflows/{file}")).unwrap()).unwrap()
    }
    fn vars(v: Value) -> Map<String, Value> {
        v.as_object().unwrap().clone()
    }

    #[test]
    fn expressions() {
        let v = vars(json!({"a": "", "b": "x", "t": true, "n": 0}));
        assert_eq!(eval("a ?? \"none\"", &v).unwrap(), json!("none"));
        assert_eq!(eval("b ?? \"none\"", &v).unwrap(), json!("x"));
        assert_eq!(eval("n ?? 5", &v).unwrap(), json!(0));
        assert_eq!(eval("t ? 50 : 8", &v).unwrap(), json!(50));
        assert_eq!(eval("n ? \"a:b\" : \"c?d\"", &v).unwrap(), json!("c?d"));
        assert_eq!(fill_str("{{b}}_v", &v).unwrap(), json!("x_v"));
        assert!(eval("missing", &v).is_err());
    }

    #[test]
    fn page_matches_the_old_graph() {
        let g = fill_graph(&moss("page.json"), &vars(json!({"style": "Colour manga", "characters": "c", "page": "p", "lora": "",
            "lora_strength": 1.0, "base_model": "", "quality": false, "versions": 3, "seed": 7, "prefix": "x/p01"}))).unwrap();
        let i = &g["1"]["inputs"];
        assert_eq!(i["character_lora"], json!("none"));
        assert_eq!(i["base_model"], json!("auto (find it by name)"));
        assert_eq!(i["speed"], json!("auto (quality only for title pages)"));
        assert_eq!(i["seed"], json!(7));
        assert_eq!(i["versions"], json!(3));
        assert_eq!(g["3"]["inputs"]["filename_prefix"], json!("x/p01_v"));
        assert_eq!(g["2"]["inputs"]["images"], json!(["1", 0]));
        assert_eq!(i["lora_2"], json!("none"));   // sft_look missing -> off
        let g = fill_graph(&moss("page.json"), &vars(json!({"style": "s", "characters": "c", "page": "p", "lora": "", "lora_strength": 1.0,
            "base_model": "", "sft_look": "moss_image_sft_look_lora.safetensors", "quality": true, "versions": 3, "seed": 7, "prefix": "x"}))).unwrap();
        assert_eq!(g["1"]["inputs"]["lora_2"], json!("moss_image_sft_look_lora.safetensors"));
        assert_eq!(g["1"]["inputs"]["lora_2_strength"], json!(1.5));
    }

    #[test]
    fn page_reading_direction_and_freeze() {
        let base = json!({"style": "s", "characters": "c", "page": "p", "lora": "", "lora_strength": 1.0, "base_model": "",
            "quality": false, "versions": 3, "seed": 7, "prefix": "x"});
        // older callers (MCP, queued jobs) without the variable keep the English reading order
        let g = fill_graph(&moss("page.json"), &vars(base.clone())).unwrap();
        assert_eq!(g["1"]["inputs"]["reading_direction"], json!("left to right"));
        // expert settings left out = auto (the node's tested recipe), the SFT look keeps 1.5
        let i = &g["1"]["inputs"];
        assert_eq!((i["sampler"].clone(), i["scheduler"].clone(), i["steps"].clone(), i["cfg"].clone()), (json!("auto"), json!("auto"), json!(0), json!(0)));
        assert_eq!((i["slg_layers"].clone(), i["negative"].clone(), i["lora_2_strength"].clone()), (json!("auto"), json!("auto"), json!(1.5)));
        let mut x = base.clone();
        x["steps"] = json!(12); x["sampler"] = json!("dpmpp_2m"); x["sft_strength"] = json!(1.2);
        let g = fill_graph(&moss("page.json"), &vars(x)).unwrap();
        assert_eq!((g["1"]["inputs"]["steps"].clone(), g["1"]["inputs"]["sampler"].clone(), g["1"]["inputs"]["lora_2_strength"].clone()),
            (json!(12), json!("dpmpp_2m"), json!(1.2)));
        let mut r = base;
        r["reading_direction"] = json!("right to left");
        assert_eq!(fill_graph(&moss("page.json"), &vars(r)).unwrap()["1"]["inputs"]["reading_direction"], json!("right to left"));
        let g = fill_graph(&moss("freeze.json"), &vars(json!({"page": "doujin_studio/D/p01_00001_.png", "items": "patterned scarf\ndenim jacket"}))).unwrap();
        assert_eq!(g["1"]["class_type"], json!("MossDoujinFreezeLook"));
        assert_eq!(g["1"]["inputs"]["items"], json!("patterned scarf\ndenim jacket"));
    }

    #[test]
    fn page_reference_is_optional() {
        let base = json!({"style": "s", "characters": "c", "page": "p", "lora": "", "lora_strength": 1.0, "base_model": "",
            "quality": false, "versions": 3, "seed": 7, "prefix": "x"});
        // no reference: the LoadImage node is gone and so is the easy node's reference input
        let g = fill_graph(&moss("page.json"), &vars(base.clone())).unwrap();
        assert!(g.get("4").is_none());
        assert!(g["1"]["inputs"].get("reference").is_none());
        assert_eq!(g["1"]["inputs"]["reference_lora"], json!("none"));
        // with a reference picture + the CharRef LoRA
        let mut r = base;
        r["reference"] = json!("fumika_refs/me.png");
        r["reference_lora"] = json!("moss_image_charref_v2.safetensors");
        r["reference_strength"] = json!(0.9);
        let g = fill_graph(&moss("page.json"), &vars(r)).unwrap();
        assert_eq!(g["4"]["class_type"], json!("LoadImage"));
        assert_eq!(g["4"]["inputs"]["image"], json!("fumika_refs/me.png"));
        assert_eq!(g["1"]["inputs"]["reference"], json!(["4", 0]));
        assert_eq!(g["1"]["inputs"]["reference_lora"], json!("moss_image_charref_v2.safetensors"));
        assert_eq!(g["1"]["inputs"]["reference_strength"], json!(0.9));
    }

    #[test]
    fn layout_full_mode_wires_slg_after_lora() {
        let base = json!({"prompt": "x", "width": 1024, "height": 1536, "base_model": "kromoss_bf16.safetensors", "text_encoder": "te",
            "vae": "v", "turbo_lora": "t", "lora": "fumika.safetensors", "lora_strength": 0.7, "full": true, "seed": 1, "prefix": "t"});
        let g = fill_graph(&moss("layout.json"), &vars(base.clone())).unwrap();
        assert_eq!(g["15"]["inputs"]["model"], json!(["14", 0]));
        assert_eq!(g["16"]["inputs"]["model"], json!(["15", 0]));
        assert_eq!(g["16"]["inputs"]["steps"], json!(50));
        assert_eq!(g["16"]["inputs"]["scheduler"], json!("sgm_uniform"));
        assert_eq!(g["13"]["inputs"]["strength_model"], json!(0.0));
        let mut t = base;
        t["full"] = json!(false);
        t["lora"] = json!("");
        let turbo = fill_graph(&moss("layout.json"), &vars(t)).unwrap();
        assert!(turbo.get("15").is_none() && turbo.get("14").is_none());
        assert_eq!(turbo["16"]["inputs"]["model"], json!(["13", 0]));
        assert_eq!(turbo["16"]["inputs"]["steps"], json!(8));
    }

    #[test]
    fn trainer_workflows_check_then_start() {
        let r = discover(Path::new("resources"));
        let anima = r.get("anima-lora-trainer").unwrap();
        let g = anima.render("train", &json!({"dataset": "D:/ds", "output_dir": "D:/out", "name": "fumika"})).unwrap();
        assert_eq!(g["1"]["inputs"]["action"], json!("check_only"));
        assert_eq!(g["6"]["inputs"]["dry_run"], json!(true));
        assert_eq!(g["3"]["inputs"]["what_are_you_training"], json!("character / person"));
        assert_eq!(g["4"]["inputs"]["gpu_vram_gb"], json!(12.0));
        let g = anima.render("train", &json!({"dataset": "D:/ds", "output_dir": "D:/out", "name": "fumika", "start": true,
            "sample_prompt": "fumika, 1girl", "sample_every": 2})).unwrap();
        assert_eq!((g["1"]["inputs"]["action"].clone(), g["6"]["inputs"]["dry_run"].clone()), (json!("install_or_update"), json!(false)));
        assert_eq!(g["6"]["inputs"]["sample_every_n_epochs"], json!(2));
        // expert overrides: left out = the wizard's presets (0 / "" / -1), given = forced
        let i = &anima.render("train", &json!({"dataset": "D:/ds", "output_dir": "D:/out", "name": "fumika"})).unwrap()["3"]["inputs"];
        assert_eq!((i["force_network_rank"].clone(), i["force_learning_rate"].clone(), i["force_resolution"].clone(), i["force_blocks_to_swap"].clone(),
            i["network_type"].clone(), i["training_seed"].clone()), (json!(0), json!(0), json!(""), json!(-1), json!("LoRA"), json!(42)));
        let g = anima.render("train", &json!({"dataset": "D:/ds", "output_dir": "D:/out", "name": "fumika", "force_rank": 16, "force_lr": 1.0,
            "force_resolution": "768,768", "force_blocks_to_swap": 0, "network_type": "LoKr", "force_epochs": 12})).unwrap();
        let i = &g["3"]["inputs"];
        assert_eq!((i["force_network_rank"].clone(), i["force_learning_rate"].clone(), i["force_resolution"].clone(), i["force_blocks_to_swap"].clone(),
            i["network_type"].clone(), i["force_max_train_epochs"].clone()), (json!(16), json!(1.0), json!("768,768"), json!(0), json!("LoKr"), json!(12)));
        let moss = r.get("moss-lora-trainer").unwrap();
        let g = moss.render("train", &json!({"dataset": "D:/ds", "name": "fumika", "start": true, "rank": 16})).unwrap();
        assert_eq!((g["1"]["inputs"]["start"].clone(), g["1"]["inputs"]["rank"].clone()), (json!(true), json!(16)));
        let sdxl = r.get("sdxl-lora-trainer").unwrap();
        let g = sdxl.render("train", &json!({"dataset": "D:/ds", "name": "fumika", "trigger": "fumika7", "rank": 16, "train_te": true})).unwrap();
        let i = &g["1"]["inputs"];
        assert_eq!((i["start"].clone(), i["rank"].clone(), i["trigger"].clone(), i["train_text_encoder"].clone(), i["v_prediction"].clone(),
            i["checkpoint"].clone()), (json!(false), json!(16), json!("fumika7"), json!(true), json!(false), json!("auto (Illustrious first)")));
        assert_eq!(sdxl.m.requires, vec!["family-sdxl".to_string()]);
        let g = sdxl.render("epochs", &json!({"name": "fumika"})).unwrap();
        assert_eq!(g["2"]["inputs"]["filename_prefix"], json!("fumika_training/fumika_epochs"));
        let sl = r.get("slider-trainer").unwrap();
        let g = sl.render("train", &json!({"family": "sdxl", "mode": "text", "name": "smile", "start": false, "rank": 8, "alpha": 4.0,
            "learning_rate": 0.0002, "guidance": 3.0, "steps": 500, "save_every": 100, "positive": "a woman, big smile", "negative": "a woman, frowning"})).unwrap();
        let i = &g["1"]["inputs"];
        assert_eq!((i["family"].clone(), i["slider_name"].clone(), i["positive"].clone(), i["neutral"].clone(), i["pos_folder"].clone(), i["checkpoint"].clone()),
            (json!("sdxl"), json!("smile"), json!("a woman, big smile"), json!("a woman"), json!(""), json!("auto (find it by name)")));
        assert_eq!(sl.m.requires_one, vec!["family-anima".to_string(), "family-anima38".to_string()]);
        let g = moss.render("epochs", &json!({"name": "fumika"})).unwrap();
        assert_eq!(g["2"]["inputs"]["filename_prefix"], json!("fumika_training/fumika_epochs"));
    }

    #[test]
    fn image_studio_workflows() {
        let reg = discover(Path::new("resources"));
        let p = reg.get("image-studio").unwrap();
        // MOSS quality T2I as images.svelte.ts plan() sends it: no turbo / SFT -> the chain is UNET -> LoRA stack -> SLG 22
        let g = p.render("t2i", &json!({"prompt": "a cat", "seed": 1, "prefix": "fumika_images/x", "width": 1024, "height": 768, "slg": "22",
            "loras": "[{\"name\": \"a.safetensors\", \"strength\": 0.8}]"})).unwrap();
        for id in ["4", "6"] { assert!(g.get(id).is_none(), "node {id} should be dropped"); }
        assert_eq!(g["5"]["inputs"]["model"], json!(["1", 0]));
        assert_eq!(g["7"]["inputs"]["model"], json!(["5", 0]));
        assert_eq!((g["10"]["class_type"].clone(), g["1"]["inputs"]["clip_type"].clone(), g["1"]["inputs"]["loader"].clone()),
            (json!("EmptyFlux2LatentImage"), json!("moss_image"), json!("split")));
        assert_eq!((g["8"]["inputs"]["clip"].clone(), g["12"]["inputs"]["vae"].clone(), g["5"]["inputs"]["clip_loras"].clone()),
            (json!(["5", 1]), json!(["1", 2]), json!(false)), "text encoders take the CLIP from the LoRA stack");
        assert_eq!((g["11"]["inputs"]["steps"].clone(), g["11"]["inputs"]["cfg"].clone(), g["11"]["inputs"]["scheduler"].clone()), (json!(50), json!(3.0), json!("sgm_uniform")));
        // Anima: own loaders, plain latent, no SLG / turbo / SFT -> the sampler takes the LoRA stack directly
        let g = p.render("t2i", &json!({"prompt": "1girl", "seed": 1, "prefix": "x", "unet": "anima-base-v1.0.safetensors",
            "text_encoder": "qwen_3_06b_base.safetensors", "vae": "qwen_image_vae.safetensors", "clip_type": "stable_diffusion",
            "latent_node": "EmptyLatentImage", "steps": 30, "cfg": 4.5, "sampler": "er_sde", "scheduler": "simple"})).unwrap();
        assert_eq!(g["11"]["inputs"]["model"], json!(["5", 0]));
        assert_eq!((g["10"]["class_type"].clone(), g["1"]["inputs"]["unet"].clone(), g["11"]["inputs"]["sampler_name"].clone()),
            (json!("EmptyLatentImage"), json!("anima-base-v1.0.safetensors"), json!("er_sde")));
        // SDXL / Illustrious: one checkpoint file, clip skip 2, LoRAs on model + text encoder
        let g = p.render("t2i", &json!({"prompt": "1girl", "seed": 1, "prefix": "x", "loader": "checkpoint", "unet": "Illustrious-XL-v2.0.safetensors",
            "clip_skip": 2, "clip_loras": true, "latent_node": "EmptyLatentImage", "steps": 28, "cfg": 5.5, "sampler": "euler_ancestral", "scheduler": "normal"})).unwrap();
        assert_eq!((g["1"]["inputs"]["loader"].clone(), g["1"]["inputs"]["clip_skip"].clone(), g["5"]["inputs"]["clip_loras"].clone()),
            (json!("checkpoint"), json!(2), json!(true)));
        assert_eq!(g["9"]["inputs"]["text"], json!(""), "no negative is forced");
        // I2I, inpaint and the upscalers read the picture through FumikaLoadSource
        let g = p.render("i2i", &json!({"prompt": "p", "seed": 1, "prefix": "x", "source": "output:a/b.png", "denoise": 0.5, "count": 2})).unwrap();
        assert_eq!((g["10"]["inputs"]["source"].clone(), g["11"]["inputs"]["denoise"].clone(), g["15"]["inputs"]["amount"].clone()), (json!("output:a/b.png"), json!(0.5), json!(2)));
        let g = p.render("inpaint", &json!({"prompt": "p", "seed": 1, "prefix": "x", "source": "output:a/b.png", "mask": "input:fumika_masks/m.png",
            "only_masked": false, "padding": 48})).unwrap();
        assert_eq!((g["40"]["inputs"]["mask"].clone(), g["41"]["inputs"]["only_masked"].clone(), g["41"]["inputs"]["padding"].clone()),
            (json!("input:fumika_masks/m.png"), json!(false), json!(48)));
        assert_eq!((g["16"]["inputs"]["mask"].clone(), g["11"]["inputs"]["latent_image"].clone(), g["13"]["inputs"]["images"].clone()),
            (json!(["41", 1]), json!(["16", 0]), json!(["42", 0])));
        let g = p.render("upscale_esrgan", &json!({"source": "output:a/b.png", "prefix": "x", "esrgan_factor": 0.5})).unwrap();
        assert_eq!(g["20"]["inputs"]["model_name"], json!("RealESRGAN_x4plus.safetensors"));
        let g = p.render("upscale_seedvr2", &json!({"source": "output:a/b.png", "prefix": "x", "seed": 3, "scale": 2.0,
            "dit": "seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors"})).unwrap();
        assert_eq!((g["10"]["inputs"]["target_scale"].clone(), g["32"]["inputs"]["resolution"].clone(), g["30"]["inputs"]["model"].clone()),
            (json!(2.0), json!(["10", 3]), json!("seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors")));
        assert!(!p.m.python.is_empty() && p.m.python.iter().all(|r| !r.starts_with("opencv") && !r.starts_with("torch")),
            "the plugin must not ask pip for opencv-python or torch");
        let g = p.render("upscale_redraw", &json!({"source": "output:a/b.png", "prefix": "x", "seed": 3, "scale": 2.0, "prompt": "p"})).unwrap();
        assert_eq!((g["10"]["inputs"]["scale"].clone(), g["11"]["inputs"]["denoise"].clone()), (json!(2.0), json!(0.3)));
    }

    #[test]
    fn asset_template_reference_and_cutout() {
        let reg = discover(Path::new("resources"));
        let p = reg.get("asset-studio").unwrap();
        // plain: no LoRA, no reference, no cutout -> the model chain collapses to UNET -> (empty) LoRA stack -> SLG
        let g = p.render("asset", &json!({"character": "Fumika: black hair", "seed": 3, "prefix": "fumika_assets/x/expressions"})).unwrap();
        for id in ["6", "7", "8", "11", "17", "18"] {
            assert!(g.get(id).is_none(), "node {id} should be dropped");
        }
        assert_eq!((g["5"]["class_type"].clone(), g["5"]["inputs"]["loras"].clone()), (json!("FumikaLoraStack"), json!("[]")));
        assert_eq!(g["9"]["inputs"]["model"], json!(["5", 0]));
        assert!(g["12"]["inputs"].get("reference").is_none());
        assert_eq!(g["1"]["inputs"]["unet_name"], json!("moss_image_base_bf16.safetensors"));
        assert_eq!(g["10"]["inputs"]["fields"], json!("{}"));
        assert_eq!(g["13"]["inputs"]["batch_size"], json!(2));
        // reference picture + SFT look + transparent sprites
        let g = p.render("asset", &json!({"character": "c", "seed": 3, "prefix": "a/b", "sft_look": "sft.safetensors",
            "reference": "fumika_refs/r.png", "reference_lora": "moss_image_charref_v2.safetensors", "transparent": true})).unwrap();
        assert_eq!(g["6"]["inputs"]["model"], json!(["5", 0]));
        assert_eq!(g["7"]["inputs"]["model"], json!(["6", 0]));
        assert_eq!(g["9"]["inputs"]["model"], json!(["8", 0]));
        assert_eq!(g["12"]["inputs"]["reference"], json!(["11", 0]));
        assert_eq!(g["11"]["inputs"]["image"], json!("fumika_refs/r.png"));
        assert_eq!(g["18"]["inputs"]["bg_removal_model"], json!(["17", 0]));
        assert_eq!(g["17"]["inputs"]["bg_removal_name"], json!("birefnet.safetensors"));
        assert_eq!(g["18"]["inputs"]["prefix"], json!("a/b_cut"));
    }

    /// writes rendered asset graphs for the engine test (cargo test dump_asset_graphs -- --ignored), FUMIKA_GRAPH_DIR = target folder
    #[test]
    #[ignore]
    fn dump_asset_graphs() {
        let reg = discover(Path::new("resources"));
        let p = reg.get("asset-studio").unwrap();
        let dir = std::env::var("FUMIKA_GRAPH_DIR").expect("FUMIKA_GRAPH_DIR");
        let character = "Fumika: an adult manga artist in her twenties with glossy black hair in a messy low ponytail with one light-blue streak in her bangs, light-blue eyes, white oversized shirt with rolled-up sleeves, black ribbon tie, black pleated skirt";
        for (name, v) in [
            ("expressions_cut", json!({"asset": "expressions", "character": character, "labels": false, "versions": 1, "seed": 99001,
                "sft_look": "moss_image_sft_look_lora.safetensors", "transparent": true, "bg_model": "birefnet.safetensors",
                "prefix": "fumika_assets/engine_test/expressions"})),
            ("pixel_cut", json!({"asset": "pixel", "character": character, "versions": 1, "seed": 7301, "transparent": true,
                "bg_model": "birefnet.safetensors", "prefix": "fumika_assets/engine_test/pixel"})),
            ("profile_ref", json!({"asset": "profile", "character": character, "versions": 1, "seed": 99004,
                "fields": "{\"quote\": \"Seven pages by tomorrow?!\"}", "sft_look": "moss_image_sft_look_lora.safetensors",
                "reference": "charref_page_ref_fumika.png", "reference_lora": "moss_image_charref_v2.safetensors",
                "prefix": "fumika_assets/engine_test/profile"})),
        ] {
            let g = p.render("asset", &v).unwrap();
            std::fs::write(format!("{dir}/{name}.json"), serde_json::to_string_pretty(&g).unwrap()).unwrap();
        }
    }

    /// rendered Image Studio graphs for the engine test (cargo test dump_image_graphs -- --ignored), vars as images.svelte.ts plan()
    #[test]
    #[ignore]
    fn dump_image_graphs() {
        let reg = discover(Path::new("resources"));
        let p = reg.get("image-studio").unwrap();
        let dir = std::env::var("FUMIKA_GRAPH_DIR").expect("FUMIKA_GRAPH_DIR");
        let src = std::env::var("FUMIKA_IMAGE_SOURCE").expect("FUMIKA_IMAGE_SOURCE");
        let mask = std::env::var("FUMIKA_IMAGE_MASK").unwrap_or_default();
        let lora = std::env::var("FUMIKA_ANIMA_LORA").unwrap_or_default();
        let prompt = "Fumika, an adult manga artist in her twenties with glossy black hair in a messy low ponytail with one light-blue streak in her bangs, light-blue eyes, white oversized shirt, sketching in a sunny park, soft watercolour anime illustration";
        let anima = json!({"unet": "anima-base-v1.0.safetensors", "text_encoder": "qwen_3_06b_base.safetensors", "vae": "qwen_image_vae.safetensors",
            "clip_type": "stable_diffusion", "latent_node": "EmptyLatentImage", "steps": 30, "cfg": 4.5, "sampler": "er_sde", "scheduler": "simple"});
        let a_prompt = "masterpiece, best quality, score_7, newest, 1girl, solo, adult woman, black hair, low ponytail, light blue streak in hair, blue eyes, white shirt, sitting on a park bench, sketchbook, holding pen, sunny day, trees";
        let a_neg = "worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts";
        let mut jobs = vec![
            ("t2i_moss", "t2i", json!({"prompt": prompt, "sft_look": "moss_image_sft_look_lora.safetensors", "slg": "22", "seed": 8101, "width": 896,
                "height": 1152, "count": 1, "prefix": "fumika_images/engine_test/t2i_moss"})),
            ("inpaint_moss", "inpaint", json!({"prompt": "close-up of the head of an adult woman with a short bright red bob haircut and black glasses, looking to the left, anime illustration", "sft_look": "moss_image_sft_look_lora.safetensors",
                "slg": "22", "seed": 8104, "source": src, "mask": mask, "denoise": 0.9, "only_masked": true, "padding": 96, "prefix": "fumika_images/engine_test/inpaint_moss"})),
        ];
        let mut a = anima.clone();
        a.as_object_mut().unwrap().extend(json!({"prompt": a_prompt, "negative": a_neg, "seed": 8201, "width": 832, "height": 1216, "count": 1,
            "prefix": "fumika_images/engine_test/t2i_anima"}).as_object().unwrap().clone());
        jobs.push(("t2i_anima", "t2i", a.clone()));
        if !lora.is_empty() {
            let mut l = a.clone();
            l["loras"] = json!(serde_json::to_string(&json!([{"name": lora, "strength": 1.0}])).unwrap());
            l["prefix"] = json!("fumika_images/engine_test/t2i_anima_lora");
            jobs.push(("t2i_anima_lora", "t2i", l));
        }
        let mut ai = anima.clone();
        ai.as_object_mut().unwrap().extend(json!({"prompt": "masterpiece, best quality, safe, 1girl, solo, portrait, adult woman, short hair, red hair, bob cut, glasses, looking to the side, white collared shirt, indoors", "negative": a_neg, "seed": 8202,
            "source": src, "mask": mask, "denoise": 0.9, "only_masked": true, "padding": 96, "prefix": "fumika_images/engine_test/inpaint_anima"}).as_object().unwrap().clone());
        jobs.push(("inpaint_anima", "inpaint", ai));
        // SDXL / Illustrious (family-sdxl family_def): one checkpoint, clip skip 2, LoRAs on model + text encoder
        let sdxl = json!({"loader": "checkpoint", "unet": "Illustrious-XL-v2.0.safetensors", "clip_skip": 2, "clip_loras": true,
            "latent_node": "EmptyLatentImage", "steps": 28, "cfg": 5.5, "sampler": "euler_ancestral", "scheduler": "normal"});
        let s_prompt = "masterpiece, best quality, amazing quality, very aesthetic, absurdres, newest, general, 1girl, solo, adult woman, black hair, low ponytail, blue streak in hair, blue eyes, white shirt, sitting on a park bench, sketchbook, holding pen, sunny day, trees";
        let s_neg = "worst quality, low quality, lowres, bad anatomy, bad hands, jpeg artifacts, watermark, signature, text";
        let mut x = sdxl.clone();
        x.as_object_mut().unwrap().extend(json!({"prompt": s_prompt, "negative": s_neg, "seed": 8301, "width": 832, "height": 1216, "count": 1,
            "prefix": "fumika_images/engine_test/t2i_sdxl"}).as_object().unwrap().clone());
        jobs.push(("t2i_sdxl", "t2i", x.clone()));
        let mut d = x.clone();
        d.as_object_mut().unwrap().extend(json!({"loras": "[{\"name\": \"DMD2\\\\dmd2_sdxl_4step_lora_fp16.safetensors\", \"strength\": 1.0}]",
            "steps": 4, "cfg": 1.0, "sampler": "lcm", "scheduler": "sgm_uniform", "prefix": "fumika_images/engine_test/t2i_sdxl_dmd2"}).as_object().unwrap().clone());
        jobs.push(("t2i_sdxl_dmd2", "t2i", d));
        let mut si = sdxl.clone();
        si.as_object_mut().unwrap().extend(json!({"prompt": "masterpiece, best quality, general, 1girl, solo, portrait, adult woman, short hair, red hair, bob cut, glasses, looking to the side, white collared shirt, indoors",
            "negative": s_neg, "seed": 8302, "source": src, "mask": mask, "denoise": 0.85, "only_masked": true, "padding": 96,
            "prefix": "fumika_images/engine_test/inpaint_sdxl"}).as_object().unwrap().clone());
        jobs.push(("inpaint_sdxl", "inpaint", si));
        for (name, wf, v) in jobs {
            let g = p.render(wf, &v).unwrap();
            std::fs::write(format!("{dir}/{name}.json"), serde_json::to_string_pretty(&g).unwrap()).unwrap();
        }
    }

    #[test]
    fn requirements_switch_on_their_family() {
        let r = discover(Path::new("resources"));
        let ids = |v: &[&str]| v.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        assert_eq!(r.with_requirements(&ids(&["moss-doujin"])), ids(&["moss-doujin", "family-moss"]));
        assert_eq!(r.with_requirements(&ids(&["image-studio"])), ids(&["image-studio", "family-moss"]), "first family when none is chosen");
        assert_eq!(r.with_requirements(&ids(&["image-studio", "family-sdxl"])), ids(&["image-studio", "family-sdxl"]));
        assert_eq!(r.with_requirements(&ids(&["anima-lora-trainer", "image-studio"])), ids(&["anima-lora-trainer", "image-studio", "family-anima"]));
        let sdxl = r.get("family-sdxl").unwrap().m.family_def.clone().unwrap();
        assert_eq!((sdxl["loader"].clone(), sdxl["clipSkip"].clone(), sdxl["clipLoras"].clone()), (json!("checkpoint"), json!(2), json!(true)));
    }

    #[test]
    fn bundled_manifests_parse() {
        let r = discover(Path::new("resources"));
        let ids: Vec<&str> = r.0.iter().map(|p| p.m.id.as_str()).collect();
        let r0: Vec<&str> = r.0.iter().map(|p| p.m.id.as_str()).collect();
        for id in ["moss-doujin", "moss-lora-trainer", "anima-lora-trainer", "asset-studio", "image-studio", "family-moss", "family-anima", "family-sdxl", "family-anima38",
                   "sdxl-lora-trainer", "slider-trainer"] {
            assert!(ids.contains(&id), "{id} missing in {ids:?}");
        }
        for p in &r.0 {
            // model family plugins only bring models + their family_def, every other plugin brings nodes
            if p.m.kinds.iter().any(|k| k == "family") {
                assert!(p.m.family_def.is_some(), "{}: a family plugin needs family_def", p.m.id);   // nodes only for its own loaders (Anima 3.8B)
            } else {
                assert!(!p.node_dirs().is_empty(), "{} has no node pack", p.m.id);
            }
            for r in p.m.requires.iter().chain(&p.m.requires_one) {
                assert!(r0.contains(&r.as_str()), "{}: requires unknown plugin {r}", p.m.id);
            }
            assert_eq!(p.node_dirs().len(), p.m.nodes.len(), "{}: a listed node pack folder is missing", p.m.id);
            assert_eq!(p.m.content, "sfw", "bundled plugins must be sfw");
            for w in p.m.workflows.values() {
                assert!(p.dir.join(&w.file).exists(), "{}: {} missing", p.m.id, w.file);
            }
        }
    }
}
