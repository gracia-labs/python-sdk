#!/usr/bin/env python3
"""Local Gradio UI for graciasdk: render splats with camera controls."""

from __future__ import annotations

import math
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

import gradio as gr
import numpy as np
from PIL import Image

_TMP_DIR = Path(tempfile.mkdtemp(prefix="gragrade_"))

from graciasdk import GraciaSDK, camera_from_bbox, camera_from_colmap

# ── COLMAP binary loader ──────────────────────────────────────────────────────

_COLMAP_NUM_PARAMS = {0: 3, 1: 4, 2: 4, 3: 5, 4: 8, 5: 8, 6: 12, 7: 5, 8: 4, 9: 5, 10: 12}


@dataclass
class _ColmapCam:
    image_id: int
    name: str
    qvec: np.ndarray
    tvec: np.ndarray
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float


def _load_colmap(images_bin: Path, cameras_bin: Path) -> list[_ColmapCam]:
    intrinsics: dict[int, dict] = {}
    with open(cameras_bin, "rb") as f:
        for _ in range(struct.unpack("<Q", f.read(8))[0]):
            cid, mid, w, h = struct.unpack("<iiqq", f.read(24))
            np_ = _COLMAP_NUM_PARAMS.get(mid, 4)
            params = struct.unpack(f"<{np_}d", f.read(8 * np_))
            if mid in (0, 2, 8):
                intrinsics[cid] = dict(w=w, h=h, fx=params[0], fy=params[0], cx=params[1], cy=params[2])
            else:
                intrinsics[cid] = dict(w=w, h=h, fx=params[0], fy=params[1], cx=params[2], cy=params[3])

    result: list[_ColmapCam] = []
    with open(images_bin, "rb") as f:
        for _ in range(struct.unpack("<Q", f.read(8))[0]):
            img_id = struct.unpack("<i", f.read(4))[0]
            qvec = np.array(struct.unpack("<4d", f.read(32)), dtype=np.float64)
            tvec = np.array(struct.unpack("<3d", f.read(24)), dtype=np.float64)
            cam_id = struct.unpack("<i", f.read(4))[0]
            name = b"".join(iter(lambda: f.read(1), b"\x00")).decode()
            n2d = struct.unpack("<Q", f.read(8))[0]
            f.read(n2d * 24)
            intr = intrinsics[cam_id]
            result.append(_ColmapCam(
                image_id=img_id, name=name, qvec=qvec, tvec=tvec,
                width=intr["w"], height=intr["h"],
                fx=intr["fx"], fy=intr["fy"], cx=intr["cx"], cy=intr["cy"],
            ))
    result.sort(key=lambda c: c.name)
    return result


# ── App state ─────────────────────────────────────────────────────────────────

_W, _H = 4096, 4096
_FOV = math.radians(60)

_sdk: GraciaSDK | None = None
_scene = None
_colmap_cameras: list[_ColmapCam] = []


def _init():
    global _sdk
    if _sdk is None:
        _sdk = GraciaSDK(_W, _H)
    return _sdk


def _to_pil(rgba: np.ndarray) -> Image.Image:
    if rgba.dtype != np.uint8:
        rgba = np.clip(rgba.astype(np.float32) * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


# ── Handlers ──────────────────────────────────────────────────────────────────

def load_scene(file_path: str | None):
    global _scene
    _invalidate_render_cache()
    if not file_path or not Path(file_path).is_file():
        _scene = None
        return gr.update(visible=False)

    try:
        _scene = _init().load(file_path)
    except Exception:
        _scene = None
        return gr.update(visible=False)

    if _scene.is_video:
        _scene.wait_ready()
    return gr.update(visible=_scene.is_video)


def load_colmap(files: list[str] | None):
    global _colmap_cameras
    _invalidate_render_cache()
    _colmap_cameras = []
    if not files:
        return gr.update(choices=[], value=None, visible=False), ""

    by_name = {Path(f).name.lower(): Path(f) for f in files}
    images_bin, cameras_bin = by_name.get("images.bin"), by_name.get("cameras.bin")

    if not images_bin or not cameras_bin:
        have = "images.bin" if images_bin else ("cameras.bin" if cameras_bin else "?")
        need = "cameras.bin" if images_bin else "images.bin"
        return gr.update(choices=[], value=None, visible=False), f"Got {have}, need {need}"

    try:
        _colmap_cameras = _load_colmap(images_bin, cameras_bin)
    except Exception as e:
        return gr.update(choices=[], value=None, visible=False), f"Error: {e}"

    choices = [c.name for c in _colmap_cameras]
    return (
        gr.update(choices=choices, value=choices[0] if choices else None, visible=True),
        f"Loaded {len(_colmap_cameras)} cameras",
    )


def _cam_info(colmap_name: str | None) -> str:
    if not colmap_name or not _colmap_cameras:
        return f"bbox camera  {_W}×{_H}  fov={math.degrees(_FOV):.0f}°"
    cc = next((c for c in _colmap_cameras if c.name == colmap_name), None)
    if not cc:
        return ""
    return (f"{cc.name}  {cc.width}×{cc.height}\n"
            f"fx={cc.fx:.1f}  fy={cc.fy:.1f}  cx={cc.cx:.1f}  cy={cc.cy:.1f}\n"
            f"qvec=[{cc.qvec[0]:.4f}, {cc.qvec[1]:.4f}, {cc.qvec[2]:.4f}, {cc.qvec[3]:.4f}]\n"
            f"tvec=[{cc.tvec[0]:.3f}, {cc.tvec[1]:.3f}, {cc.tvec[2]:.3f}]")


_cached_key = None
_cached_paths: dict[str, str] = {}


def _invalidate_render_cache() -> None:
    global _cached_key, _cached_paths
    _cached_key = None
    _cached_paths = {}


def _save(img: Image.Image, name: str) -> str:
    p = _TMP_DIR / f"{name}.png"
    img.save(p, "PNG", compress_level=1)
    return str(p)


def _do_render(video_time: float, colmap_name: str | None):
    """Re-render only if camera/time changed. Saves images to disk."""
    global _cached_key, _cached_paths
    key = (video_time, colmap_name)
    if key == _cached_key and _cached_paths:
        return

    _cached_paths = {}
    _cached_key = key

    _init()
    if _scene.is_video:
        _scene.set_time(float(video_time) * _scene.duration())

    cam = None
    if colmap_name and _colmap_cameras:
        cc = next((c for c in _colmap_cameras if c.name == colmap_name), None)
        if cc:
            cam = camera_from_colmap(
                qvec=cc.qvec, tvec=cc.tvec,
                fx=cc.fx, fy=cc.fy, cx=cc.cx, cy=cc.cy,
                width=cc.width, height=cc.height,
            )
    if cam is None:
        cam = camera_from_bbox(_scene.bbox(), _W, _H, fov_y=_FOV)

    out = _sdk.render(_scene, cam)
    _cached_paths["RGB"] = _save(_to_pil(out.color), "rgb")
    _cached_paths["Depth"] = _save(_depth_pil(out.depth), "depth")
    if out.mesh_color is not None:
        _cached_paths["Mesh"] = _save(_to_pil(out.mesh_color), "mesh")


def render(video_time: float, mode: str, colmap_name: str | None):
    if _scene is None:
        return None, _cam_info(colmap_name)
    try:
        _do_render(video_time, colmap_name)
        path = _cached_paths.get(mode)
        if path is None:
            return None, _cam_info(colmap_name)
        return path, _cam_info(colmap_name)
    except Exception:
        return None, _cam_info(colmap_name)


def _depth_pil(d: np.ndarray) -> Image.Image:
    mask = d != 0
    g = np.zeros(d.shape, dtype=np.uint8)
    if mask.any():
        v = d[mask]
        lo, hi = float(v.min()), float(v.max())
        norm = (d - lo) / (hi - lo) if hi > lo else np.where(mask, 1.0, 0.0)
        g = np.clip(np.where(mask, norm, 0.0) * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(g, "L")


# ── UI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    with gr.Blocks(title="graciasdk") as demo:
        with gr.Row():
            with gr.Column(scale=0, min_width=240):
                scene_file = gr.File(label="Scene (.ply / .sog)",
                                     file_types=[".ply", ".sog", ".mint"],
                                     file_count="single", type="filepath")
                mode = gr.Radio(["RGB", "Depth", "Mesh"], value="RGB", label="Mode")
                video_time = gr.Slider(0, 1, value=0, step=0.01, label="T", visible=False)
                gr.Markdown("---")
                colmap_file = gr.File(label="COLMAP (images.bin + cameras.bin)",
                                      file_types=[".bin"], file_count="multiple", type="filepath")
                colmap_status = gr.Textbox(label="Status", interactive=False, max_lines=1)
                colmap_select = gr.Dropdown(label="Camera", choices=[], visible=False, interactive=True)
                cam_info = gr.Textbox(label="Camera params", interactive=False, max_lines=4)
            with gr.Column(scale=1):
                preview = gr.Image(label="Preview", type="filepath", elem_id="preview")

        inputs = [video_time, mode, colmap_select]
        outputs = [preview, cam_info]
        scene_file.change(load_scene, scene_file, [video_time]).then(render, inputs, outputs)
        colmap_file.change(load_colmap, colmap_file, [colmap_select, colmap_status]).then(render, inputs, outputs)
        for inp in (video_time, mode, colmap_select):
            inp.change(render, inputs, outputs)

    demo.queue(default_concurrency_limit=1)
    import os
    host = os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1")
    demo.launch(server_name=host, inbrowser=(host == "127.0.0.1"), css="""
        #preview img { image-rendering: pixelated !important; }
    """)


if __name__ == "__main__":
    main()
