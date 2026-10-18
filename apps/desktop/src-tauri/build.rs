fn main() {
    let path=std::path::Path::new("../../../dist/release/source-manifest.json");
    println!("cargo:rerun-if-changed={}",path.display());
    let manifest=std::fs::read_to_string(path).unwrap_or_default();
    if std::env::var("PROFILE").as_deref()==Ok("release") && manifest.is_empty(){
        panic!("Build the source edition using scripts/build-source-release.py");
    }
    println!("cargo:rustc-env=SCHOLARNOTELM_SOURCE_MANIFEST={}",manifest.trim());
    tauri_build::build()
}
