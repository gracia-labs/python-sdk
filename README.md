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

Video scenes decode in the background. A seek is not instant: the decoder fetches and uploads a chunk over several turns, so the data for the time you asked for is usually not on the GPU when `set_time()` returns. `render()` waits for it, thus the simple thing works:

```python
scene = sdk.load("clip.mint")
scene.set_time(0.5 * scene.duration())    # seek, in seconds
frame = sdk.render(scene, cam)            # waits for the data for that time
```

The wait is 5 seconds per scene by default; `render(..., wait=10.0)` sets it, and `render(..., wait=False)` skips it. A timeout never raises — the frame comes back with `frame.buffering == True`, which means it is *not* the time you asked for: the frame of an earlier time, or an empty frame if nothing had decoded yet. A static scene is never buffering.

```python
frame = sdk.render(scene, cam, wait=False)   # draw whatever has decoded
if frame.buffering:
    ...                                      # not the time you asked for
```

Drive it yourself with `scene.wait_buffered(timeout=5.0)` when you want the outcome *before* you commit to a render — it returns `True` when the data is ready and `False` on timeout, and never raises, thus a render loop can skip a frame and continue. `scene.is_buffering()` is the same signal without the wait.

Each `render()` also steps the decoder once, exactly as the native players pump it every frame, so a loop that only calls `render()` keeps making progress.

`scene.wait_ready()` blocks for the **first** frame (30s timeout); `render()` does it for you. `scene.ready()` is the non-blocking poll for it — note it stays `True` afterwards, thus it does not tell you that a later seek has data. `scene.bbox()` and `scene.adaptive_bbox()` wait for ready themselves, thus they can block too.

Only video scenes can return `out.mesh_color`. For static scenes it is always `None`.

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

## Cameras in the scene

A `.mint` file can carry the COLMAP cameras that recorded it. `sdk.load()` reads and transforms them one time, thus a camera at a given time costs almost nothing to get.

```python
scene = sdk.load("clip.mint")

len(scene.cameras)                  # how many cameras the file carries
scene.camera_kinds                  # ("static", "static", …, "dynamic") — one for each camera
[c.name for c in scene.cameras]     # ("001", "002", …)

cam = scene.camera("014")           # by name, or scene.camera(13) by index
out = sdk.render(scene, cam.at(time=1.5, fps=30))
```

`cam.at(time, fps)` gives a `CameraSetup` for that time in seconds:

- A **static** camera holds one pose. It ignores the time.
- A **dynamic** camera holds one pose for each frame. `time * fps` gives the pose index: a whole index gives that pose, and an index between two poses interpolates them — the rotation along the shortest arc, and the position along a straight line. A time before the first pose or after the last pose clamps to it.

Give `set_time()` and `at()` the same time to keep the camera and the frame together. Use the frame rate that the capture ran at as `fps` — the default is 30.

The projection comes from the COLMAP intrinsics of the source image. Thus render at the aspect ratio of `cam.width / cam.height`, or resize the result to it, for an image with no distortion. The example does the second.

A static scene, and a video with no camera data, report `scene.cameras` as empty.

## API

**`GraciaSDK(width=4096, height=4096, max_splats_count=16_000_000)`**
- `.load(path) -> Scene`
- `.render(scene | [scenes], camera, model_transform=None, wait=True) -> RenderResult` — `wait` is the seconds to wait for a video scene's current time (`True` = 5s, `False` = no wait); a timeout is reported as `RenderResult.buffering`, never raised

**`Scene`**
- `.bbox() -> (min_x, min_y, min_z, max_x, max_y, max_z)` — for a video it waits for the stream to be ready, thus it can block
- `.adaptive_bbox()` — the same, with the outliers discounted
- `.count() -> int` — splat count. For a video it is the frame drawn last: `0` before the first render
- `.set_transform(m)` — 4×4 model matrix
- `.set_flag(key, value)`
- `.is_video`, `.duration()`, `.set_time(t)`, `.wait_ready(timeout=30.0)`, `.ready()`
- `.is_buffering() -> bool` — the current time has no data yet (video only)
- `.wait_buffered(timeout=5.0) -> bool` — block while it buffers; `False` on timeout, never raises
- `.cameras -> (SceneCamera, …)` — the cameras that the file carries, sorted by name
- `.camera_kinds -> ("static" | "dynamic", …)` — one for each camera, in the same order
- `.camera(name | index) -> SceneCamera`

**`SceneCamera`**
- `.at(time=0.0, fps=30.0) -> CameraSetup` — the camera to render with at that time
- `.name`, `.kind`, `.is_dynamic`, `.poses_count`
- `.width`, `.height`, `.model`, `.pinhole` — source image size and intrinsics `(fx, fy, cx, cy)`
- `.qvecs`, `.tvecs` — the COLMAP world-to-camera poses, `(N, 4)` and `(N, 3)` `float32`

**`RenderResult`**
- `.color` — RGBA `float16` `(H, W, 4)`, values in `[0, 1]`
- `.depth` — `float32` `(H, W)`, raw view-space Z (unnormalized, negative in front of the camera); `0` where nothing was hit. Normalize it yourself for display.
- `.coverage` — `float32` `(H, W)` in `[0, 1]`, the accumulated opacity of the splats
- `.mesh_color` — RGBA `uint8` `(H, W, 4)`, or `None` (video scenes only)
- `.buffering` — the frame is not the time that was asked for (video only; see [Video](#video-4dgs))

The depth of a pixel is the mean view-space Z of the splats on it, weighted by what each splat adds to the color. A pixel with coverage below `1/255` gets depth `0`, the same threshold the renderer applies.

**Multiply by `.coverage` when you show the depth.** The depth is a ratio, thus the division gives a pixel with 2 percent coverage the same full-strength Z as an opaque pixel, and every object gets a hard fringe of stray splats along its edges. The color pass has no such fringe, because a 2 percent pixel stays 2 percent bright. The multiplication puts that falloff back, and it is what the renderer does internally:

```python
out = sdk.render(scene, cam)
mask = out.coverage > 0                                    # where splats were drawn
near, far = out.depth[mask].max(), out.depth[mask].min()   # Z is negative in front

grey = (out.depth - far) / (near - far)                    # normalize, then
grey *= out.coverage                                       # keep partly covered edges faint
```

Keep `.depth` itself as it is for measurement — the multiplication is for display only. Use `.coverage` as the mask of the splats too, **not** the alpha of `.color`: the color target clears to opaque black, thus its alpha is `1` everywhere.

## Example

`examples/gradio` is a local UI. Load a scene, frame it from its bounding box or step through COLMAP cameras, switch between RGB, depth, and mesh, and scrub the timeline for 4DGS. See its [README](examples/gradio/README.md). One command:

```sh
cd examples/gradio
uv run --find-links ../../wheels --with graciasdk --with gradio gradio_app.py
```

### RGB, depth, and instance notebook

[`examples/notebooks/mint_rgb_depth_instances.ipynb`](examples/notebooks/mint_rgb_depth_instances.ipynb) is a complete MINT rendering tutorial. It selects an embedded dynamic camera with a reproducible random seed. It renders the first 30 RGB and depth frames, writes H.264 videos, and displays both videos in the notebook. It then renders every embedded instance ID at frame 0 and draws the visible masks over RGB. It does not read an external `cameras.json` file.

The companion [`requirements.txt`](examples/notebooks/requirements.txt) lists every direct dependency. Run the notebook from the repository root:

```sh
uv run --isolated --no-project --python 3.12 \
  --find-links wheels \
  --with-requirements examples/notebooks/requirements.txt \
  jupyter lab examples/notebooks/mint_rgb_depth_instances.ipynb
```

Set `MINT_PATH` in the **Settings** cell before the first run. The MINT must contain a `CAMERAS` chunk and at least one dynamic camera track.

## Troubleshooting

**`... is not a supported wheel on this platform`** — your Python is older than 3.12, or the platform or architecture of the wheel does not match your host. Check with `python -c "import sys; print(sys.version_info[:2])"`.

**`... requires a GIL-enabled interpreter`** — you are on a free-threaded build (`3.14t`). The SDK does not support it. Switch to the standard interpreter for that version.

**Import fails on a missing shared library** — install the wheel with `pip` or `uv`. Do not copy files out of `site-packages` by hand. The package works only when it is complete.

**A new wheel installs, but the old one runs** — every wheel keeps the version `0.1.0`, thus the tools match it in their cache and install the old file again. An attribute that the new wheel adds then raises `AttributeError`. Clear the cache for the package and install it again:

```sh
uv cache clean graciasdk && uv run --refresh ...
# or
pip install --no-cache-dir --force-reinstall --find-links wheels graciasdk
```

**Blank or black renders** — for a video scene, check `RenderResult.buffering`: `True` means the data for that time never arrived within the wait, and an all-black frame means nothing had decoded at all. Raise the wait (`render(..., wait=30.0)`) for a slow disk or a stream. For a static scene, check that the camera frames the geometry — `camera_from_bbox(scene.bbox(), ...)` is the safe default.

**A frame that ignores `set_time()`** — you are rendering with `wait=False` and the decoder had not caught up; the loader keeps showing the last good frame while it buffers. `RenderResult.buffering` flags exactly that.

**GPU initialization fails** — confirm a Vulkan-capable driver (Windows/Linux) or macOS 11 or later for Metal. Headless Linux still needs a real GPU device and driver.

## Contributing

Contributions are welcome — bug fixes, new examples, platform fixes, documentation.

- **Everything under the MIT part of [LICENSE](LICENSE)** — issues and pull requests both. Fork it, patch it, send it back.
- **The Artifacts** — issues only. They ship prebuilt, thus there is nothing to patch here. Report a bug with steps to reproduce it and we fix it upstream and ship a new build.

By opening a pull request you agree that your contribution is licensed under the MIT License (Part B of [LICENSE](LICENSE)).
