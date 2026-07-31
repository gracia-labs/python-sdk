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

from graciasdk import DEFAULT_FPS, GraciaSDK, camera_from_bbox, camera_from_colmap

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
_instances: list[tuple[int, str]] = []
_scene_cameras: tuple = ()


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

def _instance_update():
    choices = [("All classes", 0)] + [(name, iid) for iid, name in _instances]
    return gr.update(choices=choices, value=0, visible=bool(_instances))


def _camera_update():
    choices = [("Off", -1)] + [
        (f"{c.name} ({c.kind})", i) for i, c in enumerate(_scene_cameras)
    ]
    return (gr.update(choices=choices, value=-1, visible=bool(_scene_cameras)),
            gr.update(visible=any(c.is_dynamic for c in _scene_cameras)))


def load_scene(file_path: str | None):
    global _scene, _instances, _scene_cameras
    _invalidate_render_cache()
    _instances = []
    _scene_cameras = ()
    if not file_path or not Path(file_path).is_file():
        _scene = None
        return (gr.update(visible=False), _instance_update(), *_camera_update())

    try:
        _scene = _init().load(file_path)
    except Exception:
        _scene = None
        return (gr.update(visible=False), _instance_update(), *_camera_update())

    if _scene.is_video:
        try:
            _scene.wait_ready()
        except RuntimeError:
            _scene = None
            return (gr.update(visible=False), _instance_update(), *_camera_update())
        _instances = sorted(_scene.instance_names().items())
        _scene_cameras = _scene.cameras
    return (gr.update(visible=_scene.is_video), _instance_update(), *_camera_update())


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


def _camera_at(index: int | None):
    if index is None or not (0 <= index < len(_scene_cameras)):
        return None
    return _scene_cameras[index]


def _clip_seconds(video_time: float) -> float:
    """The end of the clip is exclusive: a seek to the duration shows nothing."""
    if not (_scene and _scene.is_video):
        return 0.0
    duration = _scene.duration()
    return min(float(video_time) * duration, max(0.0, duration - 1e-6))


def _cam_info(colmap_name: str | None, camera_index: int | None,
              video_time: float, fps: float) -> str:
    sc = _camera_at(camera_index)
    if sc is not None:
        fx, fy, cx, cy = sc.pinhole
        pose = min(max(_clip_seconds(video_time) * float(fps), 0.0), sc.poses_count - 1)
        return (f"scene camera {sc.name} ({sc.kind})  {sc.width}×{sc.height}\n"
                f"fx={fx:.1f}  fy={fy:.1f}  cx={cx:.1f}  cy={cy:.1f}\n"
                f"pose {pose:.2f} of {sc.poses_count - 1}  at {fps:g} fps")
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


def _save(img: Image.Image, name: str, size: tuple[int, int] | None = None) -> str:
    p = _TMP_DIR / f"{name}.png"
    if size and size != img.size:
        img = img.resize(size, Image.LANCZOS)
    img.save(p, "PNG", compress_level=1)
    return str(p)


def _display_size(width: int, height: int) -> tuple[int, int]:
    """The square render holds the full camera frame, thus the preview needs the
    aspect ratio of the source image to show it without distortion."""
    scale = min(_W / width, _H / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _do_render(video_time: float, colmap_name: str | None, instance_id: int | None,
               camera_index: int | None, fps: float):
    """Re-render only if camera/time/class changed. Saves images to disk."""
    global _cached_key, _cached_paths
    key = (video_time, colmap_name, instance_id, camera_index, fps)
    if key == _cached_key and _cached_paths:
        return

    _cached_paths = {}
    _cached_key = key

    _init()
    if _scene.is_video:
        _scene.set_time(_clip_seconds(video_time))
        if not _scene.wait_buffered():
            _invalidate_render_cache()   # nothing to draw yet: keep the last frame
            raise RuntimeError("buffering")
    _scene.set_uint("instance_filter", int(instance_id or 0))

    cam, size = None, None
    sc = _camera_at(camera_index)
    if sc is not None:
        cam = sc.at(_clip_seconds(video_time), float(fps))
        size = _display_size(sc.width, sc.height)
    elif colmap_name and _colmap_cameras:
        cc = next((c for c in _colmap_cameras if c.name == colmap_name), None)
        if cc:
            cam = camera_from_colmap(
                qvec=cc.qvec, tvec=cc.tvec,
                fx=cc.fx, fy=cc.fy, cx=cc.cx, cy=cc.cy,
                width=cc.width, height=cc.height,
            )
            size = _display_size(cc.width, cc.height)
    if cam is None:
        cam = camera_from_bbox(_scene.bbox(), _W, _H, fov_y=_FOV)

    out = _sdk.render(_scene, cam)
    _cached_paths["RGB"] = _save(_to_pil(out.color), "rgb", size)
    _cached_paths["Depth"] = _save(_depth_pil(out.depth, out.coverage), "depth", size)
    if out.mesh_color is not None:
        _cached_paths["Mesh"] = _save(_to_pil(out.mesh_color), "mesh", size)


def render(video_time: float, mode: str, colmap_name: str | None,
           instance_id: int | None, camera_index: int | None, fps: float):
    fps = float(fps) if fps else DEFAULT_FPS
    info = _cam_info(colmap_name, camera_index, video_time, fps)
    if _scene is None:
        return None, info
    try:
        _do_render(video_time, colmap_name, instance_id, camera_index, fps)
        return _cached_paths.get(mode), info
    except RuntimeError as e:
        return None, f"{info}\n{e}" if str(e) == "buffering" else info
    except Exception:
        return None, info


def _depth_pil(d: np.ndarray, coverage: np.ndarray) -> Image.Image:
    """Depth is a ratio, thus a barely covered pixel gets a full-strength value
    and the edges get a hard fringe. Multiply by the coverage to give the edges
    the same falloff that the colour has."""
    mask = d != 0
    g = np.zeros(d.shape, dtype=np.float32)
    if mask.any():
        v = d[mask]
        lo, hi = float(v.min()), float(v.max())
        g[mask] = (v - lo) / (hi - lo) if hi > lo else 1.0
    g *= np.clip(coverage, 0.0, 1.0)
    return Image.fromarray(np.clip(g * 255.0, 0, 255).astype(np.uint8), "L")


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
                instance_select = gr.Dropdown(label="Class", choices=[("All classes", 0)],
                                              value=0, visible=False, interactive=True)
                camera_select = gr.Dropdown(label="Scene camera", choices=[("Off", -1)],
                                             value=-1, visible=False, interactive=True)
                camera_fps = gr.Number(label="Camera fps", value=DEFAULT_FPS, minimum=1,
                                        step=1, visible=False, interactive=True)
                gr.Markdown("---")
                colmap_file = gr.File(label="COLMAP (images.bin + cameras.bin)",
                                      file_types=[".bin"], file_count="multiple", type="filepath")
                colmap_status = gr.Textbox(label="Status", interactive=False, max_lines=1)
                colmap_select = gr.Dropdown(label="Camera", choices=[], visible=False, interactive=True)
                cam_info = gr.Textbox(label="Camera params", interactive=False, max_lines=4)
            with gr.Column(scale=1):
                preview = gr.Image(label="Preview", type="filepath", elem_id="preview")

        inputs = [video_time, mode, colmap_select, instance_select, camera_select, camera_fps]
        outputs = [preview, cam_info]
        scene_outputs = [video_time, instance_select, camera_select, camera_fps]
        scene_file.change(load_scene, scene_file, scene_outputs).then(render, inputs, outputs)
        colmap_file.change(load_colmap, colmap_file, [colmap_select, colmap_status]).then(render, inputs, outputs)
        for inp in (video_time, mode, colmap_select, instance_select, camera_select, camera_fps):
            inp.change(render, inputs, outputs)

    demo.queue(default_concurrency_limit=1)
    import os
    host = os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1")
    demo.launch(server_name=host, inbrowser=(host == "127.0.0.1"), css="""
        #preview img { image-rendering: pixelated !important; }
    """)


if __name__ == "__main__":
    main()
