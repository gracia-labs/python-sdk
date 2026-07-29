# Gracia Python SDK

Python bindings for the Gracia Gaussian-splat renderer. The renderer supports 3DGS (static) and 4DGS (video). The SDK renders on the GPU and returns the result as NumPy arrays.

This repository ships **prebuilt wheels**. There is nothing to compile.

```
wheels/            prebuilt graciasdk wheels, one per platform
examples/gradio/   local UI: load a scene, pick a camera, preview RGB/depth/mesh
```

## Requirements

- CPython 3.12 or newer — one wheel for each platform covers every version
- A standard interpreter with the GIL enabled — **the SDK does not support free-threaded builds (`3.13t`, `3.14t`, …)**
- GPU and driver: Vulkan on Windows/Linux, Metal on macOS 11 or later (Apple silicon only — the SDK does not support Intel Macs)
- `numpy` (the wheel pulls it in automatically) — every render output is a NumPy array

## Install

```sh
uv pip install --find-links wheels graciasdk
# or
python -m pip install --find-links wheels graciasdk
```

You can also name the file:

```sh
uv pip install wheels/graciasdk-0.1.0-cp312-abi3-win_amd64.whl
```

Install straight from GitHub, with no clone:

```sh
pip install https://github.com/gracia-labs/python-sdk/raw/main/wheels/graciasdk-0.1.0-cp312-abi3-win_amd64.whl
```

The `cp312` in the file name is a *floor*, not an exact match. The same file installs on 3.12, 3.13, 3.14, and later. You only need to select your platform.

| Host | Wheel |
| --- | --- |
| Windows x64 | `cp312-abi3-win_amd64` |
| macOS Apple Silicon | `cp312-abi3-macosx_11_0_arm64` |
| Linux x64 | `cp312-abi3-manylinux_*_x86_64` |

Only the platforms in `wheels/` are available. The SDK does not support Python 3.11 and older.

**The SDK does not support free-threaded Python.** These wheels need an interpreter with the GIL enabled. Thus they do not install on `3.13t`, `3.14t`, or any other free-threaded build. pip reports the wheel as incompatible, and does not fail at run time. Use a standard interpreter.

## Quickstart

```python
from graciasdk import GraciaSDK, camera_from_bbox

sdk = GraciaSDK(1024, 1024)              # GPU context + renderer — create once, render many
scene = sdk.load("scene.ply")

cam = camera_from_bbox(scene.bbox(), 1024, 1024)
out = sdk.render(scene, cam)

out.color        # (H, W, 4) float16 RGBA, values in [0, 1]
out.depth        # (H, W)    float32, raw view-space Z (unnormalized); 0 where nothing was hit
out.mesh_color   # (H, W, 4) uint8 RGBA, or None
```

Save it as a PNG:

```python
import numpy as np
from PIL import Image

rgba = np.clip(out.color.astype(np.float32) * 255, 0, 255).astype(np.uint8)
Image.fromarray(rgba, "RGBA").save("render.png")
```

The render size is fixed when you construct `GraciaSDK`. Thus the camera aspect must match it. Several scenes can share one frame: `sdk.render([scene_a, scene_b], cam)`.

## Scene formats

| Extension | Contents |
| --- | --- |
| `.ply` | static 3DGS |
| `.sog` | static, compressed |
| `.mint` | video 4DGS |

Only `.mint` loads as a video stream. The SDK treats every other extension as a static scene.

## Demo content

Scenes to play with: **https://docs.gracia.ai/demo-data**

Download them and load them with `sdk.load(...)`. This SDK plays local files only. The [Apple](https://github.com/gracia-labs/apple-sdk) and [C/C++](https://github.com/gracia-labs/c-cpp-sdk) SDKs can also stream a scene: from a direct URL, which works from any static host, or through Gracia infrastructure with a token, which is the more reliable path.

They are demo content: for demonstration and evaluation, not for redistribution or publication. See [CONTENT-LICENSE](CONTENT-LICENSE). For your own 4DGS content, write to support@gracia.ai.

## Video (4DGS)

Video scenes decode in the background. Wait for the first frames before you render:

```python
scene = sdk.load("clip.mint")
scene.wait_ready()                        # blocks, 30s timeout by default
scene.set_time(0.5 * scene.duration())    # seek, in seconds
frame = sdk.render(scene, cam)
```

`scene.ready()` is the non-blocking poll. Only video scenes can return `out.mesh_color`. For static scenes it is always `None`.

## Cameras

A `CameraSetup` is a projection matrix with a camera-to-world transform. Both are 4×4 column-major float32. The projection is the Vulkan style: depth in `[0, 1]`, Y flipped.

```python
import math
import numpy as np
from graciasdk import camera_from_bbox, camera_from_colmap, look_at, perspective, make_camera

# Frame the whole scene
cam = camera_from_bbox(scene.bbox(), 1024, 1024, fov_y=math.radians(60))

# Reproduce a COLMAP view (handles COLMAP's Y-down / Z-forward convention)
cam = camera_from_colmap(qvec, tvec, fx, fy, cx, cy, width, height)

# Custom rig — make_camera wants camera-to-world, so invert the view matrix
view = look_at(eye=(0, 0, 5), center=(0, 0, 0))
cam = make_camera(perspective(math.radians(60), 1.0, 0.1, 100.0),
                  np.ascontiguousarray(np.linalg.inv(view.T).T))
```

## API

**`GraciaSDK(width=4096, height=4096, max_splats_count=16_000_000)`**
- `.load(path) -> Scene`
- `.render(scene | [scenes], camera, model_transform=None) -> RenderResult`

**`Scene`**
- `.bbox() -> (min_x, min_y, min_z, max_x, max_y, max_z)`
- `.count() -> int` — splat count
- `.set_transform(m)` — 4×4 model matrix
- `.set_flag(key, value)`
- `.is_video`, `.duration()`, `.set_time(t)`, `.wait_ready(timeout=30.0)`, `.ready()`

**`RenderResult`**
- `.color` — RGBA `float16` `(H, W, 4)`, values in `[0, 1]`
- `.depth` — `float32` `(H, W)`, raw view-space Z (unnormalized, negative in front of the camera); `0` where nothing was hit. Normalize it yourself for display.
- `.mesh_color` — RGBA `uint8` `(H, W, 4)`, or `None` (video scenes only)

## Example

`examples/gradio` is a local UI. Load a scene, frame it from its bounding box or step through COLMAP cameras, switch between RGB, depth, and mesh, and scrub the timeline for 4DGS. See its [README](examples/gradio/README.md). One command:

```sh
cd examples/gradio
uv run --find-links ../../wheels --with graciasdk --with gradio gradio_app.py
```

## Troubleshooting

**`... is not a supported wheel on this platform`** — your Python is older than 3.12, or the platform or architecture of the wheel does not match your host. Check with `python -c "import sys; print(sys.version_info[:2])"`.

**`... requires a GIL-enabled interpreter`** — you are on a free-threaded build (`3.14t`). The SDK does not support it. Switch to the standard interpreter for that version.

**Import fails on a missing shared library** — install the wheel with `pip` or `uv`. Do not copy files out of `site-packages` by hand. The package works only when it is complete.

**Blank or black renders** — for video scenes, call `wait_ready()` before the first `render()`. For static scenes, check that the camera frames the geometry. `camera_from_bbox(scene.bbox(), ...)` is the safe default.

**GPU initialization fails** — confirm a Vulkan-capable driver (Windows/Linux) or macOS 11 or later for Metal. Headless Linux still needs a real GPU device and driver.

## Contributing

Contributions are welcome — bug fixes, new examples, platform fixes, documentation.

- **Everything under the MIT part of [LICENSE](LICENSE)** — issues and pull requests both. Fork it, patch it, send it back.
- **The Artifacts** — issues only. They ship prebuilt, thus there is nothing to patch here. Report a bug with steps to reproduce it and we fix it upstream and ship a new build.

By opening a pull request you agree that your contribution is licensed under the MIT License (Part B of [LICENSE](LICENSE)).
