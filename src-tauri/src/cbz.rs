//! CBZ export of a chapter: the chosen page versions (and the cover) as 000.png, 001.png ... plus ComicInfo.xml (series,
//! chapter number, title, reading direction, "AI-generated" note) in a stored (uncompressed) ZIP - PNGs are compressed
//! already, and comic readers (CDisplayEx, YACReader, Komga, Kavita, Mihon) read stored ZIPs fastest.
use std::io::Write;

use crate::config::Config;

/// a page URL of the web view (".../view?filename=x.png&subfolder=a/b&type=output") -> the file in ComfyUI/output
fn output_of(c: &Config, url: &str) -> anyhow::Result<std::path::PathBuf> {
    let q = url.split_once('?').map(|(_, q)| q).unwrap_or("");
    let get = |k: &str| q.split('&').find_map(|kv| kv.strip_prefix(&format!("{k}="))).map(crate::pct_decode).unwrap_or_default();
    if get("type") != "output" {
        anyhow::bail!("only rendered pages can be exported");
    }
    crate::comfy::output_file(c, &get("subfolder"), &get("filename"))
}

/// stored ZIP: local headers, data, central directory (no compression, no data descriptors)
fn zip_store(entries: &[(String, Vec<u8>)]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut central = Vec::new();
    for (name, data) in entries {
        let crc = crc32fast::hash(data);
        let off = out.len() as u32;
        let (n, len) = (name.as_bytes(), data.len() as u32);
        // local file header
        out.extend_from_slice(&[0x50, 0x4b, 0x03, 0x04, 20, 0, 0, 0, 0, 0, 0, 0, 0x21, 0]);   // v2.0, no flags, stored, time 0, date 1980-01-01
        out.extend_from_slice(&crc.to_le_bytes());
        out.extend_from_slice(&len.to_le_bytes());
        out.extend_from_slice(&len.to_le_bytes());
        out.extend_from_slice(&(n.len() as u16).to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out.extend_from_slice(n);
        out.extend_from_slice(data);
        // central directory entry
        central.extend_from_slice(&[0x50, 0x4b, 0x01, 0x02, 20, 0, 20, 0, 0, 0, 0, 0, 0, 0, 0x21, 0]);
        central.extend_from_slice(&crc.to_le_bytes());
        central.extend_from_slice(&len.to_le_bytes());
        central.extend_from_slice(&len.to_le_bytes());
        central.extend_from_slice(&(n.len() as u16).to_le_bytes());
        central.extend_from_slice(&[0; 12]);   // extra, comment, disk, internal attrs, external attrs (2+2+2+2+4)
        central.extend_from_slice(&off.to_le_bytes());
        central.extend_from_slice(n);
    }
    let cd_off = out.len() as u32;
    out.extend_from_slice(&central);
    out.extend_from_slice(&[0x50, 0x4b, 0x05, 0x06, 0, 0, 0, 0]);
    out.extend_from_slice(&(entries.len() as u16).to_le_bytes());
    out.extend_from_slice(&(entries.len() as u16).to_le_bytes());
    out.extend_from_slice(&(central.len() as u32).to_le_bytes());
    out.extend_from_slice(&cd_off.to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes());
    out
}

/// write `dest` (a .cbz the user picked): pages in order (the cover first when there is one) + ComicInfo.xml; returns the page count
pub fn export(c: &Config, dest: &str, pages: &[String], comic_info: &str) -> anyhow::Result<usize> {
    if pages.is_empty() {
        anyhow::bail!("no finished pages");
    }
    let mut entries = Vec::with_capacity(pages.len() + 1);
    for (i, url) in pages.iter().enumerate() {
        let p = output_of(c, url)?;
        let ext = p.extension().and_then(|x| x.to_str()).unwrap_or("png").to_lowercase();
        let bytes = std::fs::read(&p)?;
        entries.push((format!("{i:03}.{ext}"), if c.export_strip_prompt { crate::aimark::strip_prompt(&bytes) } else { bytes }));
    }
    entries.push(("ComicInfo.xml".into(), comic_info.as_bytes().to_vec()));
    let dest = std::path::PathBuf::from(dest);
    let tmp = dest.with_extension("cbz.part");
    std::fs::File::create(&tmp)?.write_all(&zip_store(&entries))?;
    std::fs::rename(&tmp, &dest)?;
    Ok(pages.len())
}

#[cfg(test)]
mod tests {
    #[test]
    fn stored_zip_has_valid_headers_and_crcs() {
        let z = super::zip_store(&[("000.png".into(), b"abc".to_vec()), ("ComicInfo.xml".into(), b"<x/>".to_vec())]);
        assert!(z.starts_with(&[0x50, 0x4b, 0x03, 0x04]));
        let end = &z[z.len() - 22..];
        assert_eq!(&end[..4], &[0x50, 0x4b, 0x05, 0x06]);
        assert_eq!(u16::from_le_bytes([end[10], end[11]]), 2);
        // first entry: name, data and CRC where the header says
        assert_eq!(u32::from_le_bytes(z[14..18].try_into().unwrap()), crc32fast::hash(b"abc"));
        assert_eq!(&z[30..37], b"000.png");
        assert_eq!(&z[37..40], b"abc");
        // the central directory starts where the end record points
        let cd = u32::from_le_bytes(end[16..20].try_into().unwrap()) as usize;
        assert_eq!(&z[cd..cd + 4], &[0x50, 0x4b, 0x01, 0x02]);
    }
}

#[cfg(test)]
mod real_zip {
    #[test]
    #[ignore]
    fn write_a_zip_for_python() {
        let png = std::fs::read(std::env::var("PNG").unwrap()).unwrap();
        let z = super::zip_store(&[("000.png".into(), png), ("ComicInfo.xml".into(), b"<?xml version=\"1.0\"?><ComicInfo><Series>T</Series></ComicInfo>".to_vec())]);
        std::fs::write(std::env::var("OUT").unwrap(), z).unwrap();
    }
}
