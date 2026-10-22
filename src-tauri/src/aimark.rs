//! Machine-readable "AI-generated" marking of every picture Fumika renders (EU AI Act Art. 50(2)): a finished job's PNGs get
//! an XMP packet with the IPTC digital source type `trainedAlgorithmicMedia` (read by Adobe, Google, Meta, C2PA tools) and
//! `Software` / `Description` text chunks, next to ComfyUI's own workflow chunks. Exports copy the marked files.
use serde_json::Value;
use std::path::Path;

const XMP_KEY: &[u8] = b"XML:com.adobe.xmp";
const SOURCE_TYPE: &str = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia";
const SOFTWARE: &str = concat!("Fumika ", env!("CARGO_PKG_VERSION"));

fn chunk(kind: &[u8; 4], data: &[u8]) -> Vec<u8> {
    let mut c = (data.len() as u32).to_be_bytes().to_vec();
    c.extend_from_slice(kind);
    c.extend_from_slice(data);
    let mut h = crc32fast::Hasher::new();
    h.update(kind);
    h.update(data);
    c.extend_from_slice(&h.finalize().to_be_bytes());
    c
}

fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

/// "AI-generated image (Fumika 0.1.0; models: a)"
pub fn description(models: &[String]) -> String {
    if models.is_empty() {
        format!("AI-generated image ({SOFTWARE})")
    } else {
        format!("AI-generated image ({SOFTWARE}; models: {})", models.join(", "))
    }
}

fn xmp(desc: &str) -> String {
    format!(concat!(
        "<?xpacket begin=\"\u{feff}\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>",
        "<x:xmpmeta xmlns:x=\"adobe:ns:meta/\"><rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">",
        "<rdf:Description rdf:about=\"\" xmlns:Iptc4xmpExt=\"http://iptc.org/std/Iptc4xmpExt/2008-02-29/\" ",
        "xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:xmp=\"http://ns.adobe.com/xap/1.0/\" ",
        "Iptc4xmpExt:DigitalSourceType=\"{}\" xmp:CreatorTool=\"{}\">",
        "<dc:description><rdf:Alt><rdf:li xml:lang=\"x-default\">{}</rdf:li></rdf:Alt></dc:description>",
        "</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end=\"w\"?>"), SOURCE_TYPE, SOFTWARE, esc(desc))
}

/// the XMP packet as an iTXt chunk
fn xmp_chunk(desc: &str) -> Vec<u8> {
    let mut itxt = XMP_KEY.to_vec();
    itxt.extend_from_slice(&[0, 0, 0, 0, 0]);   // end of keyword, no compression, method 0, empty language + translated keyword
    itxt.extend_from_slice(xmp(desc).as_bytes());
    chunk(b"iTXt", &itxt)
}

/// a text chunk: tEXt when the text is Latin-1, else iTXt (UTF-8) - Pillow / A1111 do the same for "parameters"
fn text_chunk(key: &str, text: &str) -> Vec<u8> {
    if text.chars().all(|c| (c as u32) < 256) {
        let mut d = key.as_bytes().to_vec();
        d.push(0);
        d.extend(text.chars().map(|c| c as u32 as u8));
        chunk(b"tEXt", &d)
    } else {
        let mut d = key.as_bytes().to_vec();
        d.extend_from_slice(&[0, 0, 0, 0, 0]);
        d.extend_from_slice(text.as_bytes());
        chunk(b"iTXt", &d)
    }
}

/// width and height from IHDR
pub fn png_size(png: &[u8]) -> Option<(u32, u32)> {
    if png.len() < 24 || &png[12..16] != b"IHDR" {
        return None;
    }
    Some((u32::from_be_bytes(png[16..20].try_into().ok()?), u32::from_be_bytes(png[20..24].try_into().ok()?)))
}

/// The PNG with the marking chunks after IHDR (+ A1111 "parameters" when given); None = not a PNG or already marked.
pub fn mark_png_bytes(png: &[u8], desc: &str) -> Option<Vec<u8>> {
    mark_png_with(png, desc, None)
}

pub fn mark_png_with(png: &[u8], desc: &str, params: Option<&str>) -> Option<Vec<u8>> {
    const SIG: &[u8] = b"\x89PNG\r\n\x1a\n";
    if !png.starts_with(SIG) || png.len() < 33 || &png[12..16] != b"IHDR" {
        return None;
    }
    // walk the chunks: stop if an XMP packet is there already
    let mut i = 8;
    while i + 12 <= png.len() {
        let len = u32::from_be_bytes(png[i..i + 4].try_into().ok()?) as usize;
        let kind = &png[i + 4..i + 8];
        if kind == b"iTXt" && png.get(i + 8..i + 8 + XMP_KEY.len()) == Some(XMP_KEY) {
            return None;
        }
        if kind == b"IEND" {
            break;
        }
        i += 12 + len;
    }
    let ihdr_end = 8 + 12 + u32::from_be_bytes(png[8..12].try_into().ok()?) as usize;
    if ihdr_end > png.len() {
        return None;
    }
    let mut out = png[..ihdr_end].to_vec();
    out.extend(xmp_chunk(desc));
    out.extend(chunk(b"tEXt", format!("Software\0{SOFTWARE}").as_bytes()));
    // tEXt is Latin-1: one byte per character, others as '?' (the XMP keeps the exact UTF-8 text)
    let mut text = b"Description\0".to_vec();
    text.extend(desc.chars().map(|c| u8::try_from(c as u32).unwrap_or(b'?')));
    out.extend(chunk(b"tEXt", &text));
    if let Some(p) = params {
        out.extend(text_chunk("parameters", p));
    }
    out.extend_from_slice(&png[ihdr_end..]);
    Some(out)
}

/// For sharing without the recipe: drop ComfyUI's graph ("prompt", "workflow") and the A1111 "parameters" (they name LoRAs,
/// paths and the story), keep the AI marking; the description loses the model names. Not a PNG -> unchanged.
pub fn strip_prompt(png: &[u8]) -> Vec<u8> {
    const SIG: &[u8] = b"\x89PNG\r\n\x1a\n";
    if !png.starts_with(SIG) {
        return png.to_vec();
    }
    let mut out = SIG.to_vec();
    let mut i = 8;
    while i + 12 <= png.len() {
        let len = u32::from_be_bytes(png[i..i + 4].try_into().unwrap()) as usize;
        let end = (i + 12 + len).min(png.len());
        let kind = &png[i + 4..i + 8];
        let data = &png[i + 8..(i + 8 + len).min(png.len())];
        let key = data.split(|b| *b == 0).next().unwrap_or(&[]);
        let text = matches!(kind, b"tEXt" | b"iTXt" | b"zTXt");
        if text && matches!(key, b"prompt" | b"workflow" | b"parameters") {
            // dropped
        } else if text && key == b"Description" {
            out.extend(text_chunk("Description", &description(&[])));
        } else if kind == b"iTXt" && key == XMP_KEY {
            // the XMP repeats the description: same marking, without the model names
            out.extend(xmp_chunk(&description(&[])));
        } else {
            out.extend_from_slice(&png[i..end]);
        }
        if kind == b"IEND" {
            break;
        }
        i += 12 + len;
    }
    out
}

/// copy a rendered picture for an export, without the prompt data when the user asked for that (Setup)
pub fn export_copy(src: &Path, dst: &Path, strip: bool) -> std::io::Result<()> {
    if !strip || !src.extension().is_some_and(|x| x.eq_ignore_ascii_case("png")) {
        return std::fs::copy(src, dst).map(|_| ());
    }
    std::fs::write(dst, strip_prompt(&std::fs::read(src)?))
}

pub fn mark_png(p: &Path, desc: &str) -> anyhow::Result<bool> {
    mark_png_params(p, desc, None, None)
}

/// mark one picture; with a graph also the A1111 "parameters" (size from this picture, hashes from the engine's models)
pub fn mark_png_params(p: &Path, desc: &str, c: Option<&crate::config::Config>, graph: Option<&Value>) -> anyhow::Result<bool> {
    let png = std::fs::read(p)?;
    let params = graph.zip(png_size(&png)).and_then(|(g, (w, h))| crate::genparams::parameters(c, g, w, h));
    let Some(out) = mark_png_with(&png, desc, params.as_deref()) else { return Ok(false) };
    let tmp = p.with_extension("png.part");
    std::fs::write(&tmp, out)?;
    let mut res = std::fs::rename(&tmp, p);
    for _ in 0..3 {
        if res.is_ok() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(300));
        res = std::fs::rename(&tmp, p);
    }
    if let Err(e) = res {
        let _ = std::fs::remove_file(&tmp);
        return Err(e.into());
    }
    Ok(true)
}

/// checkpoint / diffusion model files a ComfyUI graph loads, for the description (LoRA names stay out: they can name private characters)
pub fn graph_models(graph: &Value) -> Vec<String> {
    let mut out: Vec<String> = graph.as_object().into_iter().flat_map(|g| g.values())
        .flat_map(|n| ["ckpt_name", "unet_name"].into_iter().filter_map(move |k| n["inputs"][k].as_str()))
        .map(|f| f.rsplit(['/', '\\']).next().unwrap_or(f).trim_end_matches(".safetensors").trim_end_matches(".gguf").to_string())
        .collect();
    out.sort();
    out.dedup();
    out
}

/// mark the saved pictures of a finished job ({node: {images: [{filename, subfolder, type}]}}); previews in temp/ are skipped
pub fn mark_outputs(c: &crate::config::Config, outputs: &Value, graph: Option<&Value>) {
    let desc = description(&graph.map(graph_models).unwrap_or_default());
    for im in outputs.as_object().into_iter().flat_map(|o| o.values()).flat_map(|v| v["images"].as_array().into_iter().flatten()) {
        let name = im["filename"].as_str().unwrap_or("");
        if im["type"] != "output" || !name.to_lowercase().ends_with(".png") {
            continue;
        }
        if let Ok(p) = crate::comfy::output_file(c, im["subfolder"].as_str().unwrap_or(""), name) {
            if let Err(e) = mark_png_params(&p, &desc, Some(c), graph) {
                eprintln!("AI marking of {} failed: {e}", p.display());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tiny_png() -> Vec<u8> {
        let mut p = b"\x89PNG\r\n\x1a\n".to_vec();
        p.extend(chunk(b"IHDR", &[0, 0, 0, 1, 0, 0, 0, 1, 8, 0, 0, 0, 0]));
        p.extend(chunk(b"tEXt", b"prompt\0{}"));
        p.extend(chunk(b"IDAT", &[0x78, 0x9c, 0x63, 0x60, 0x00, 0x00, 0x00, 0x02, 0x00, 0x01]));
        p.extend(chunk(b"IEND", &[]));
        p
    }

    #[test]
    fn marks_once_and_keeps_the_picture() {
        let png = tiny_png();
        let d = description(&["kromoss_v10_bf16".into()]);
        let m = mark_png_bytes(&png, &d).unwrap();
        let s = String::from_utf8_lossy(&m);
        assert!(s.contains("trainedAlgorithmicMedia") && s.contains("Software\0Fumika") && s.contains("kromoss_v10_bf16"));
        assert!(m.ends_with(&png[33..]), "IHDR stays first, the rest of the file is untouched");
        assert!(mark_png_bytes(&m, &d).is_none(), "second pass changes nothing");
        assert!(mark_png_bytes(b"GIF89a....", &d).is_none());
        // every chunk's CRC is valid
        let mut i = 8;
        while i < m.len() {
            let len = u32::from_be_bytes(m[i..i + 4].try_into().unwrap()) as usize;
            let crc = crc32fast::hash(&m[i + 4..i + 8 + len]);
            assert_eq!(crc.to_be_bytes(), m[i + 8 + len..i + 12 + len]);
            i += 12 + len;
        }
    }

    #[test]
    fn parameters_chunk_and_strip() {
        let m = mark_png_with(&tiny_png(), "AI-generated image (x)", Some("a cat\nSteps: 30, Size: 1x1")).unwrap();
        assert!(String::from_utf8_lossy(&m).contains("parameters\0a cat\nSteps: 30"));
        let u = mark_png_with(&tiny_png(), "d", Some("ネコ")).unwrap();   // not Latin-1 -> iTXt, UTF-8
        assert!(u.windows(4).filter(|w| *w == b"iTXt").count() == 2 && String::from_utf8_lossy(&u).contains("ネコ"));
        let named = mark_png_bytes(&tiny_png(), &description(&["secret_model".into()])).unwrap();
        assert!(!String::from_utf8_lossy(&strip_prompt(&named)).contains("secret_model"), "model names leave the XMP too");
        let s = strip_prompt(&m);
        let t = String::from_utf8_lossy(&s);
        assert!(!t.contains("parameters") && !t.contains("prompt\0") && t.contains("trainedAlgorithmicMedia") && t.contains("Software\0Fumika"));
        assert!(s.ends_with(&m[m.len() - 12..]), "IEND stays");
        assert_eq!(png_size(&m), Some((1, 1)));
    }

    #[test]
    fn models_come_from_the_graph() {
        let g = serde_json::json!({"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "moss\\miaomiao.safetensors"}},
            "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": "charref_v2.safetensors", "model": ["1", 0]}},
            "3": {"class_type": "KSampler", "inputs": {"seed": 1}}});
        assert_eq!(graph_models(&g), vec!["miaomiao"]);
    }
}

#[cfg(test)]
mod real_file {
    #[test]
    #[ignore]
    fn mark_a_real_comfyui_png() {
        let p = std::path::PathBuf::from(std::env::var("PNG").unwrap());
        assert!(super::mark_png(&p, &super::description(&["kromoss_v10_bf16".into()])).unwrap());
    }
}
