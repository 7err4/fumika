//! cargo run --release --example extract_test -- <archive.7z> <out dir>
//! Checks that the pure-Rust 7z decoder can unpack the official ComfyUI portable archive, and how long it takes.
fn main() {
    let a: Vec<String> = std::env::args().collect();
    let t = std::time::Instant::now();
    sevenz_rust2::decompress_file(&a[1], &a[2]).expect("extract failed");
    let ok = std::path::Path::new(&a[2]).join("ComfyUI_windows_portable/python_embeded/python.exe").exists();
    println!("extracted in {:.0}s, python.exe present: {ok}", t.elapsed().as_secs_f64());
}
