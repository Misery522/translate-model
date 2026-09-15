const publicShellAssetPattern =
    /^(index\.html|manifest\.webmanifest|pet-icon\.svg|pet-icon-(?:192|512|maskable-512)\.png|apple-touch-icon\.png|assets\/[^/]+\.(js|css|svg|woff2))$/;

export function isPublicShellAsset(path) {
    return publicShellAssetPattern.test(path);
}
