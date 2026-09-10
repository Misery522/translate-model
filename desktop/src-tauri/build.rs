fn main() {
    let manifest = tauri_build::AppManifest::new().commands(&[
        "configure_backend",
        "backend_status",
        "api_request",
    ]);
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(manifest))
        .expect("desktop build configuration is invalid");
}
