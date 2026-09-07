"""仅公开构建后的静态界面，不能把项目目录或私有数据当作网站发布。"""

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

PUBLIC_FILES = frozenset({
    "index.html", "manifest.webmanifest", "sw.js", "pet-icon.svg", "THIRD_PARTY_LICENSES.txt",
})
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; worker-src 'self'; object-src 'none'; "
    "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
)


class StaticShell(StaticFiles):
    async def get_response(self, path, scope):
        # Starlette 在 Windows 上会用系统路径分隔符归一化 URL。
        path = path.replace("\\", "/")
        # 本阶段是单页首页；未知路径返回 404，不能把 API 错误变成缓存的 HTML。
        if path in {"", "."}:
            path = "index.html"
        is_asset = (
            path.startswith("assets/")
            and len(Path(path).parts) == 2
            and Path(path).suffix in {".js", ".css", ".svg", ".woff2"}
        )
        if path not in PUBLIC_FILES and not is_asset:
            raise HTTPException(404)
        response = await super().get_response(path, scope)
        response.headers.update(
            {
                "Content-Security-Policy": CSP,
                "X-Frame-Options": "DENY",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Cache-Control": "public, max-age=31536000, immutable" if is_asset else "no-cache",
            }
        )
        return response


def mount_static_shell(app: FastAPI, directory: Path) -> None:
    directory = directory.resolve(strict=True)
    if not directory.is_dir() or not (directory / "index.html").is_file():
        raise ValueError("静态界面尚未构建，请先运行前端构建命令。")
    app.mount("/", StaticShell(directory=directory, html=False, follow_symlink=False), name="web")
