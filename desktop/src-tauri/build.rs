mod generated_icon {
    include!("src/generated_icon.rs");
}
fn main() {
    // Reproducible generated icon: tracked source stays UTF-8 text only.
    let hex="89504e470d0a1a0a0000000d4948445200000020000000200806000000737a7af40000003049444154789cedce21010000080330d2508348f45710e366627ed5b39754020202020202020202020202020202e9c003cc6e4c6a8a70a4780000000049454e44ae426082";
    let icon: Vec<u8> = (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap())
        .collect();
    generated_icon::ensure_icon(std::path::Path::new("."), &icon)
        .expect("Generated icon conflict; existing user files were preserved");
    tauri_build::build()
}
