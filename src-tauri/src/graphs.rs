//! Helpers around ComfyUI job outputs. The graphs themselves are workflow templates of the plugins (plugins.rs).
use serde_json::Value;

/// All images of a finished job's outputs as /view query strings, in node order.
pub fn image_queries(outputs: &Value) -> Vec<String> {
    let mut nodes: Vec<(&String, &Value)> = outputs.as_object().map(|o| o.iter().collect()).unwrap_or_default();
    nodes.sort_by_key(|(k, _)| k.parse::<u64>().unwrap_or(u64::MAX));
    nodes
        .into_iter()
        .flat_map(|(_, v)| v.get("images").and_then(|i| i.as_array()).cloned().unwrap_or_default())
        .map(|im| {
            let s = |k: &str| im.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
            format!("filename={}&subfolder={}&type={}", enc(&s("filename")), enc(&s("subfolder")), enc(&s("type")))
        })
        .collect()
}

fn enc(s: &str) -> String {
    s.bytes()
        .map(|b| if b.is_ascii_alphanumeric() || b"-_.~".contains(&b) { (b as char).to_string() } else { format!("%{b:02X}") })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn image_queries_are_ordered_and_encoded() {
        let out = json!({"3": {"images": [{"filename": "b c.png", "subfolder": "s/x", "type": "output"}]},
                          "2": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}});
        assert_eq!(image_queries(&out), vec!["filename=a.png&subfolder=&type=output", "filename=b%20c.png&subfolder=s%2Fx&type=output"]);
    }
}
