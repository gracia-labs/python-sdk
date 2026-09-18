#!/usr/bin/env python3
"""Local Gradio UI for graciasdk: render splats with camera controls."""

from __future__ import annotations

import itertools
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path

import gradio as gr
import numpy as np

from graciasdk import (HAND_EDGES, GraciaSDK, camera_from_bbox, camera_from_colmap, draw_flow_arrows,
                       draw_points, flow_colors)

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

_LONG_SIDE = 1536   # the render's longer side: the preview's size, so nothing renders that the page scales away
_FOV = math.radians(60)
_BBOX = -1
_CLOUD_COLORS = ((1.0, 0.25, 0.25), (0.25, 0.7, 1.0), (0.3, 1.0, 0.4), (1.0, 0.85, 0.2))
_FLOW_MODES = ("Flow", "Flow arrows")

_sdk: GraciaSDK | None = None
_scene = None
_view = None
_bbox_camera = None
_colmap_cameras: list[_ColmapCam] = []
_colmap_setups: dict[str, object] = {}


def _init() -> GraciaSDK:
    global _sdk
    if _sdk is None:
        _sdk = GraciaSDK()
    return _sdk


def _fit(width: int, height: int) -> tuple[int, int]:
    """The render size with the aspect ratio of the source image and ``_LONG_SIDE`` as its longer side."""
    scale = _LONG_SIDE / max(width, height)
    return max(1, round(width * scale)), max(1, round(height * scale))


# ── Handlers ──────────────────────────────────────────────────────────────────

def _instance_update():
    names = sorted(_scene.instance_names().items()) if _scene else []
    choices = [("All classes", 0)] + [(name, iid) for iid, name in names]
    return gr.update(choices=choices, value=0, visible=bool(names))


def _camera_update():
    cameras = _scene.cameras if _scene else ()
    choices = [("Bounding box", _BBOX)] + [(f"{c.name} ({c.kind})", i) for i, c in enumerate(cameras)]
    label = f"Scene camera ({len(cameras)} in the file)" if cameras else "Scene camera (none in the file)"
    return gr.update(choices=choices, value=_BBOX, label=label, visible=_scene is not None)


def _scene_updates():
    """The time and flow time show for a video only."""
    video = bool(_scene and _scene.is_video)
    clouds = bool(_scene and _scene.point_clouds)
    return (gr.update(visible=video), gr.update(visible=video),
            _instance_update(), _camera_update(), gr.update(value=False, visible=clouds))


def load_scene(file_path: str | None):
    global _scene, _view, _bbox_camera
    _scene, _view, _bbox_camera = None, None, None
    if file_path and Path(file_path).is_file():
        try:
            scene = _init().load(file_path)
            scene.wait_ready()
            _scene = scene
        except Exception:
            _scene = None
    return _scene_updates()


def load_colmap(files: list[str] | None):
    global _colmap_cameras, _colmap_setups
    _colmap_cameras, _colmap_setups = [], {}
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


def _clip_seconds(video_time: float) -> float:
    """The end of the clip is exclusive: a seek to the duration shows nothing."""
    if not (_scene and _scene.is_video):
        return 0.0
    duration = _scene.duration()
    return min(float(video_time) * duration, max(0.0, duration - 1e-6))


def _camera(colmap_name: str | None, camera_index: int | None):
    """The camera, its render size, and what the camera box states: a scene camera, then a COLMAP one, then the bounding box."""
    global _bbox_camera
    cameras = _scene.cameras
    if camera_index is not None and 0 <= camera_index < len(cameras):
        sc = cameras[camera_index]
        fx, fy, cx, cy = sc.pinhole
        poses = f"{sc.poses_count} poses over the track" if sc.is_dynamic else "one pose"
        return sc, _fit(sc.width, sc.height), (f"scene camera {sc.name} ({sc.kind})  {sc.width}×{sc.height}\n"
                                               f"fx={fx:.1f}  fy={fy:.1f}  cx={cx:.1f}  cy={cy:.1f}\n{poses}")
    cc = next((c for c in _colmap_cameras if c.name == colmap_name), None)
    if cc:
        if cc.name not in _colmap_setups:
            _colmap_setups[cc.name] = camera_from_colmap(qvec=cc.qvec, tvec=cc.tvec, fx=cc.fx, fy=cc.fy, cx=cc.cx,
                                                         cy=cc.cy, width=cc.width, height=cc.height)
        return _colmap_setups[cc.name], _fit(cc.width, cc.height), (
            f"{cc.name}  {cc.width}×{cc.height}\n"
            f"fx={cc.fx:.1f}  fy={cc.fy:.1f}  cx={cc.cx:.1f}  cy={cc.cy:.1f}\n"
            f"qvec=[{cc.qvec[0]:.4f}, {cc.qvec[1]:.4f}, {cc.qvec[2]:.4f}, {cc.qvec[3]:.4f}]\n"
            f"tvec=[{cc.tvec[0]:.3f}, {cc.tvec[1]:.3f}, {cc.tvec[2]:.3f}]")
    if _bbox_camera is None:
        _bbox_camera = camera_from_bbox(_scene.bbox(), _LONG_SIDE, _LONG_SIDE, fov_y=_FOV)
    return _bbox_camera, (_LONG_SIDE, _LONG_SIDE), f"bounding box camera  fov={math.degrees(_FOV):.0f}°"


def _with_clouds(image: np.ndarray) -> np.ndarray:
    width = image.shape[1]
    for (cloud, points), color in zip(_view.points, itertools.cycle(_CLOUD_COLORS)):
        edges = HAND_EDGES if len(points) == 21 else ()
        draw_points(image, _view.camera_setup, points, edges, color, square=max(2, width // 250), line=max(1, width // 700))
    return image


def _depth_image(depth: np.ndarray, coverage: np.ndarray) -> np.ndarray:
    """Depth is a ratio, thus a barely covered pixel gets a full-strength value and the edges get a hard fringe.
    Multiply by the coverage to give the edges the same falloff that the colour has."""
    mask = depth != 0
    g = np.zeros(depth.shape, dtype=np.float32)
    if mask.any():
        v = depth[mask]
        lo, hi = float(v.min()), float(v.max())
        g[mask] = (v - lo) / (hi - lo) if hi > lo else 1.0
    g *= np.clip(coverage, 0.0, 1.0)
    return (g * 255.0).astype(np.uint8)


def render(video_time: float, mode: str, colmap_name: str | None, instance_id: int | None, camera_index: int | None,
           clouds: bool, flow_time: float):
    global _view
    if _scene is None:
        return None, ""
    camera, (width, height), info = _camera(colmap_name, camera_index)
    t = _clip_seconds(video_time)
    if _view is None:
        _view = _init().view(_scene, camera, width, height, time=t)
    _view.camera, _view.width, _view.height, _view.time = camera, width, height, t

    try:
        image, note = _output(mode, bool(clouds), flow_time)
    except Exception as e:
        return None, f"{info}\n{e}"
    if _view.buffering:
        note = f"{note}\nbuffering: the data for this time did not arrive".strip()
    return image, f"{info}\n{note}".strip()


def _output(mode: str, clouds: bool, flow_time: float):
    """The image of the mode with the point clouds over it when asked, and a note."""
    image, note = _mode_image(mode, flow_time)
    if clouds and image is not None:
        image = _with_clouds(np.repeat(image[..., None], 3, axis=2) if image.ndim == 2 else image.copy())
    return image, note


def _mode_image(mode: str, flow_time: float):
    """The image of the mode and a note; only the output the mode shows renders."""
    if mode == "Depth":
        return _depth_image(_view.depth, _view.coverage), ""
    if mode not in _FLOW_MODES:
        return _view.color8, ""

    reference = _clip_seconds(flow_time)
    if _scene.is_video and reference == _view.time:
        return None, "Flow to T is T"
    flow = _view.flow(reference)
    if flow is None:
        return None, "no flow in this scene"
    colors, scale = flow_colors(flow.flow, flow.coverage)
    note = f"flow scale {scale:.2f} px, {float((flow.coverage > 0.01).mean()):.1%} covered"
    if mode == "Flow":
        return colors, note
    return draw_flow_arrows(_view.color8.copy(), flow.flow, flow.coverage, colors), note


def set_instance(instance_id: int | None):
    if _scene is not None:
        _scene.set_uint("instance_filter", int(instance_id or 0))


# ── UI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    with gr.Blocks(title="graciasdk") as demo:
        with gr.Row():
            with gr.Column(scale=0, min_width=240):
                scene_file = gr.File(label="Scene (.ply, .sog or a 4DGS video)",
                                     file_count="single", type="filepath")
                mode = gr.Radio(["RGB", "Depth", *_FLOW_MODES], value="RGB", label="Mode")
                camera_select = gr.Dropdown(label="Scene camera", choices=[("Bounding box", _BBOX)],
                                            value=_BBOX, visible=False, interactive=True)
                video_time = gr.Slider(0, 1, value=0, step=0.01, label="T", visible=False)
                flow_time = gr.Slider(0, 1, value=0, step=0.01, label="Flow to T", visible=False)
                instance_select = gr.Dropdown(label="Class", choices=[("All classes", 0)],
                                              value=0, visible=False, interactive=True)
                clouds_toggle = gr.Checkbox(label="Point clouds", value=False, visible=False)
                gr.Markdown("---")
                colmap_file = gr.File(label="COLMAP (images.bin + cameras.bin)",
                                      file_types=[".bin"], file_count="multiple", type="filepath")
                colmap_status = gr.Textbox(label="Status", interactive=False, max_lines=1)
                colmap_select = gr.Dropdown(label="Camera", choices=[], visible=False, interactive=True)
                cam_info = gr.Textbox(label="Camera params", interactive=False, max_lines=6)
            with gr.Column(scale=1):
                preview = gr.Image(label="Preview", type="numpy", format="png", elem_id="preview")

        inputs = [video_time, mode, colmap_select, instance_select, camera_select, clouds_toggle, flow_time]
        outputs = [preview, cam_info]
        scene_outputs = [video_time, flow_time, instance_select, camera_select, clouds_toggle]
        scene_file.change(load_scene, scene_file, scene_outputs).then(render, inputs, outputs)
        colmap_file.change(load_colmap, colmap_file, [colmap_select, colmap_status]).then(render, inputs, outputs)
        instance_select.change(set_instance, instance_select, None).then(render, inputs, outputs)
        for inp in inputs:
            if inp is not instance_select:
                inp.change(render, inputs, outputs)

    demo.queue(default_concurrency_limit=1)
    host = os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1")
    demo.launch(server_name=host, inbrowser=(host == "127.0.0.1"), css="""
        #preview img { image-rendering: pixelated !important; }
    """)


if __name__ == "__main__":
    main()
