# Gracia Python SDK

Python bindings for the Gracia Gaussian-splat renderer. The renderer supports 3DGS (static) and 4DGS (video). The SDK renders on the GPU and returns the result as NumPy arrays.

This repository ships **prebuilt wheels**. There is nothing to compile.

```
wheels/              prebuilt graciasdk wheels, one per platform
examples/gradio/     local UI: load a scene, pick a camera, preview RGB/depth/flow
examples/notebooks/  a video tutorial: RGB and depth videos, instance overlay
```

## Requirements

- CPython 3.12 or newer — one wheel for each platform covers every version
- A standard interpreter with the GIL enabled — **the SDK does not support free-threaded builds (`3.13t`, `3.14t`, …)**
- GPU and driver: Vulkan on Windows/Linux, Metal on macOS 11 or later (Apple silicon only — the SDK does not support Intel Macs)
- `numpy` (the wheel pulls it in automatically) — every output of a view is a NumPy array

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

sdk = GraciaSDK()                        # GPU context + renderer — create once
scene = sdk.load("scene.ply")

cam = camera_from_bbox(scene.bbox(), 1024, 1024)
view = sdk.view(scene, cam, 1024, 1024)

view.color8      # (H, W, 4) uint8 RGBA — renders now
view.depth       # (H, W)    float32, raw view-space Z (unnormalized); 0 where nothing was hit
```

Save it as a PNG:

```python
from PIL import Image

Image.fromarray(view.color8, "RGBA").save("render.png")
```

## Views

A `View` holds what to look at: the scenes, the camera, the time, and the size. The state lives in Python. An output renders when you read it, and then it stays until the view changes. An output that you do not read does not render.

```python
view = sdk.view(scene, cam, 1280, 720, time=0.0)
view.color8          # renders the color
view.color8          # the same array, no render
view.time = 0.5      # a change: every output renders again when you read it
view.depth           # renders the depth for 0.5, not the color
```

Set a field to change the view: `scenes`, `camera`, `width`, `height`, `time`, `model_transform`, `wait`. A change to a scene, for example `scene.set_uint(...)`, renders the outputs of its views again too. Each view can have its own size, and several scenes can share one frame: `sdk.view([scene_a, scene_b], cam, 1024, 1024)`.

The camera aspect must match the aspect of the view.

## Scene formats

| Extension | Contents |
| --- | --- |
| `.ply` | static 3DGS |
| `.sog` | static, compressed |
| `.mint` | video 4DGS |
| any other | video 4DGS; such a file can also carry the cameras of the capture, the instance labels and point clouds |

`.ply`, `.sog` and `.guf` load as a static scene. The SDK loads every other file as a video stream.

## Demo content

Scenes to play with: **https://docs.gracia.ai/demo-data**

Download them and load them with `sdk.load(...)`. This SDK plays local files only. The [Apple](https://github.com/gracia-labs/apple-sdk) and [C/C++](https://github.com/gracia-labs/c-cpp-sdk) SDKs can also stream a scene: from a direct URL, which works from any static host, or through Gracia infrastructure with a token, which is the more reliable path.

They are demo content: for demonstration and evaluation, not for redistribution or publication. See [CONTENT-LICENSE](CONTENT-LICENSE). For your own 4DGS content, write to support@gracia.ai.

## Video (4DGS)

Video scenes decode in the background. A seek is not instant: the decoder fetches and uploads a chunk over several turns. A view seeks its videos to `view.time` and waits for the data before it renders, thus the simple thing works:

```python
scene = sdk.load("path/to/video")
view = sdk.view(scene, cam, 1024, 1024, time=0.5 * scene.duration())
view.color8                               # waits for the data for that time
```

The wait is 5 seconds for each scene by default. `sdk.view(..., wait=10.0)` sets it, and `wait=False` skips it. A timeout never raises: `view.buffering` becomes `True`, which means that an output is *not* the time that you asked for. It shows an earlier time, or nothing if nothing had decoded yet. A static scene is never buffering.

A view first waits for the **first** frame of a video (30 s timeout), and it raises `RuntimeError` when that times out. `scene.wait_ready()`, `scene.ready()`, `scene.wait_buffered(timeout=5.0)` and `scene.is_buffering()` give the same signals without a view. `scene.bbox()` and `scene.adaptive_bbox()` wait for ready themselves, thus they can block too.

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
view_matrix = look_at(eye=(0, 0, 5), center=(0, 0, 0))
cam = make_camera(perspective(math.radians(60), 1.0, 0.1, 100.0),
                  np.ascontiguousarray(np.linalg.inv(view_matrix.T).T))
```

## Cameras in the scene

A 4DGS video can carry the COLMAP cameras that recorded it. The scene reads them from the file when you first use them.

```python
scene = sdk.load("path/to/video")

len(scene.cameras)                  # how many cameras the file carries
scene.camera_kinds                  # ("static", "static", …, "dynamic") — one for each camera
[c.name for c in scene.cameras]     # ("001", "002", …)

cam = scene.camera("014")           # by name, or scene.camera(13) by index
view = sdk.view(scene, cam, cam.width, cam.height, time=1.5)
```

A view takes a `SceneCamera` as it is and uses it at `view.time`, thus the camera and the frame stay together. `cam.at(time)` gives the `CameraSetup` for a time in seconds:

- A **static** camera holds one pose. It ignores the time.
- A **dynamic** camera holds one pose for each frame, spread evenly over the track: pose `i` is at `begin + i * (end - begin) / cam.poses_count`, where `begin` and `end` are the first and the last instant of the track. Between two poses the camera interpolates them — the rotation along the shortest arc, and the position along a straight line. A time before the first pose or after the last pose clamps to it.

The projection comes from the COLMAP intrinsics of the source image. Thus render at the aspect ratio of `cam.width / cam.height` for an image with no distortion.

A static scene and a video with no camera data report `scene.cameras` as empty.

## Instances in the scene

A 4DGS video can label each splat with the segmentation instance that it belongs to. `scene.instance_names()` gives the name of each instance by id, and `instance_filter` renders one of them as a mask:

```python
scene.instance_names()                    # {1: "knife_0", 2: "knife_1", …}
scene.set_uint("instance_filter", 1)      # instance 1 in white, every other splat in black
mask = view.color8[..., 0]
scene.set_uint("instance_filter", 0)      # the colors again
```

Every splat still takes part in visibility, thus an object in front of the instance hides it in the mask. A static scene and a video with no segmentation report no instance names, and the filter does not change them.

## Point clouds in the scene

A video's track can carry point clouds, for example the hands of the capture. Each `PointCloud` holds one set of points for each frame, spread evenly over the track in the same way as the poses of a dynamic camera. The scene reads them from the file when you first use them.

```python
from graciasdk import HAND_EDGES, draw_points

hand = next(p for p in scene.point_clouds if p.name == "hand_0")
hand.positions.shape                      # (F, N, 3) float32, NaN where a frame has no data
points = hand.at(1.5)                     # (N, 3) at that time in seconds

image = view.color8.copy()                # the view keeps its array: draw into a copy
for cloud, points in view.points:         # each point cloud at view.time
    draw_points(image, view.camera_setup, points, HAND_EDGES, color=(1.0, 0.2, 0.2))
```

`hand.at(time)` moves each point along a line between the two frames around the time. A point with no data in either frame is NaN.

`draw_points(image, camera, points, edges)` projects the points with the camera. It draws a square at each point and a line for each edge `(a, b)` into the image, in place. The image is a float image in `[0, 1]` or an 8-bit image, with 3 or 4 channels. A NaN point, or a point behind the camera, draws nothing. The drawing goes over the splats, and it does not test depth. `HAND_EDGES` is the 20 bones between the 21 keypoints of a hand.

A static scene and a video with no point clouds report `scene.point_clouds` as empty.

## API

**`GraciaSDK(max_splats_count=16_000_000)`**
- `.load(path) -> Scene`
- `.view(scene | [scenes], camera, width, height, time=0.0, model_transform=None, wait=True) -> View` — `camera` is a `CameraSetup` or a `SceneCamera`; `wait` is the seconds to wait for the data of a video's time (`True` = 5 s, `False` = no wait)

**`View`** — every output renders when you first read it, and stays until a field or a scene changes
- `.scenes`, `.camera`, `.width`, `.height`, `.time`, `.model_transform`, `.wait` — set one to change the view
- `.color` — RGBA `float16` `(H, W, 4)`, values in `[0, 1]`
- `.color8` — RGBA `uint8` `(H, W, 4)`, `.color` rounded to bytes
- `.depth` — `float32` `(H, W)`, raw view-space Z (unnormalized, negative in front of the camera); `0` where nothing was hit. Normalize it yourself for display.
- `.coverage` — `float32` `(H, W)` in `[0, 1]`, the accumulated opacity of the splats; it renders with `.depth`
- `.flow(reference_time) -> FlowResult | None` — the flow from `.time` to `reference_time`; `None` when no scene has flow. See [Flow](#flow)
- `.points -> ((PointCloud, (N, 3)), …)` — each point cloud of the scenes at `.time`
- `.camera_setup -> CameraSetup` — the camera at `.time`
- `.buffering` — an output since the last change is not the time that was asked for (video only; see [Video](#video-4dgs))

The arrays of a view belong to the view: copy an array before you draw into it.

**`Scene`**
- `.bbox() -> (min_x, min_y, min_z, max_x, max_y, max_z)` — for a video it waits for the stream to be ready, thus it can block
- `.adaptive_bbox()` — the same, with the outliers discounted
- `.count() -> int` — splat count. For a video it is the frame drawn last: `0` before the first render
- `.set_transform(m)` — 4×4 model matrix
- `.set_flag(key, value)` — `"sh3"` for the view-dependent color, `"mip"` for the antialiasing filter. Every scene loads with `"mip"` on, except a video whose track turns it off
- `.set_uint(key, value)` — `"instance_filter"`: the id of the instance to render as a mask, `0` for the colors
- `.instance_names() -> {id: name}` — the instances that a video labels its splats with
- `.is_video`, `.duration()`, `.set_time(t)`, `.wait_ready(timeout=30.0)`, `.ready()`
- `.is_buffering() -> bool` — the current time has no data yet (video only)
- `.wait_buffered(timeout=5.0) -> bool` — block while it buffers; `False` on timeout, never raises
- `.cameras -> (SceneCamera, …)` — the cameras that the file carries, sorted by name
- `.camera_kinds -> ("static" | "dynamic", …)` — one for each camera, in the same order
- `.camera(name | index) -> SceneCamera`
- `.point_clouds -> (PointCloud, …)` — the point clouds that the file carries, in the order of the file

**`SceneCamera`**
- `.at(time=0.0) -> CameraSetup` — the camera to render with at that time
- `.name`, `.kind`, `.is_dynamic`, `.poses_count`
- `.width`, `.height`, `.model`, `.pinhole` — source image size and intrinsics `(fx, fy, cx, cy)`
- `.qvecs`, `.tvecs` — the COLMAP world-to-camera poses, `(N, 4)` and `(N, 3)` `float32`

**`PointCloud`**
- `.at(time=0.0) -> (N, 3)` — the points at that time, NaN where there is no data
- `.name`, `.positions` — `(F, N, 3)` `float32`, the frames spread evenly over the track

**`draw_points(image, camera, points, edges=(), color=(1.0, 0.25, 0.25), square=6, line=2) -> image`** — draw squares at the points and lines along the edges, in place; `HAND_EDGES` is the edges of a hand

**`flow_colors(flow, coverage, scale=0.0) -> (colors, scale)`** — `FlowResult.flow` as RGB `uint8` `(H, W, 3)` on the Middlebury color wheel, and the scale that it used. The hue is the direction. A move of `scale` pixels or more is full color, and no move is white. `scale` `0` is the 95th percentile of the moves, or `1` when nothing moves. Each color is multiplied by the `coverage` of its pixel, so edges fade to black as the depth does for display. A pixel with `coverage` at `0.01` or below is black

**`draw_flow_arrows(image, flow, coverage, colors, step=28) -> image`** — draw an arrow of the flow every `step` pixels, from pixel `20`, in place. A pixel with `coverage` at `0.1` or below, or with a move below `0.5` pixels, has no arrow. All arrows draw 3 pixels wide in a dark color first, then 1 pixel wide in the color of their pixel in `colors`

The depth of a pixel is the mean view-space Z of the splats on it, weighted by what each splat adds to the color. A pixel with coverage below `1/255` gets depth `0`, the same threshold the renderer applies.

**Multiply by `.coverage` when you show the depth.** The depth is a ratio, thus the division gives a pixel with 2 percent coverage the same full-strength Z as an opaque pixel, and every object gets a hard fringe of stray splats along its edges. The color pass has no such fringe, because a 2 percent pixel stays 2 percent bright. The multiplication puts that falloff back, and it is what the renderer does internally:

```python
mask = view.coverage > 0                                     # where splats were drawn
near, far = view.depth[mask].max(), view.depth[mask].min()   # Z is negative in front

grey = (view.depth - far) / (near - far)                     # normalize, then
grey *= view.coverage                                        # keep partly covered edges faint
```

Keep `.depth` itself as it is for measurement — the multiplication is for display only. Use `.coverage` as the mask of the splats too, **not** the alpha of `.color`: the color target clears to opaque black, thus its alpha is `1` everywhere.

**`FlowResult`**
- `.flow` — `float32` `(H, W, 2)`, the move of the splats in pixels; see [Flow](#flow)
- `.coverage` — `float32` `(H, W)` in `[0, 1]`, the accumulated opacity of the splats that `.flow` measures
- `.buffering` — a video had no data for one of the two times

### Flow

`view.flow(reference_time)` does not render colors. A flow frame measures each splat against the flow frame of its scene before it. `flow` makes that flow frame itself, thus `reference_time` and `view.time` must differ for a video, or `ValueError` comes back. Each video goes to `reference_time`, waits, and prepares a flow frame that draws nothing. Then each video goes back to `view.time`, waits again, and draws a flow frame against the first one.

The flow of a pixel is the mean move of the splats on it, weighted by what each splat adds to the color. A move goes from where a splat is at `view.time`, seen from the camera at `view.time`, to where the same splat is at `reference_time`, seen from the camera at `reference_time`. Thus a dynamic camera that moves adds flow: a static table moves in the image when the camera moves. `x` points right and `y` points down the image rows, so a pixel `(x, y)` moves to `(x + flow[..., 0], y + flow[..., 1])`. Only a splat at both times adds to the flow, and `.coverage` is the opacity of those splats. A pixel with `.coverage` below `1/255` gets flow `0`. Only a video whose splats carry ids has flow. For every other scene, `flow` gives `None`.

```python
from graciasdk import draw_flow_arrows, flow_colors

view.time = 1.0
flow = view.flow(1.2)
colors, scale = flow_colors(flow.flow, flow.coverage)           # (H, W, 3) uint8
arrows = draw_flow_arrows(view.color8.copy(), flow.flow, flow.coverage, colors)
```

## Example

`examples/gradio` is a local UI. Load a scene, frame it from its bounding box, from the cameras a video carries or from COLMAP cameras, switch between RGB, depth, and flow, scrub the timeline for 4DGS, isolate one instance, and draw the point clouds. See its [README](examples/gradio/README.md). One command:

```sh
cd examples/gradio
uv run --find-links ../../wheels --with graciasdk --with gradio gradio_app.py
```

### RGB, depth, and instance notebook

[`examples/notebooks/video_rgb_depth_instances.ipynb`](examples/notebooks/video_rgb_depth_instances.ipynb) is a complete video rendering tutorial. It selects an embedded dynamic camera with a reproducible random seed. It renders the first 30 RGB and depth frames, writes H.264 videos, and displays both videos in the notebook. It then renders every embedded instance ID at time 0 and draws the visible masks over RGB. It does not read an external `cameras.json` file.

The companion [`requirements.txt`](examples/notebooks/requirements.txt) lists every direct dependency. Run the notebook from the repository root:

```sh
uv run --isolated --no-project --python 3.12 \
  --find-links wheels \
  --with-requirements examples/notebooks/requirements.txt \
  jupyter lab examples/notebooks/video_rgb_depth_instances.ipynb
```

Set `VIDEO_PATH` in the **Settings** cell before the first run. The video must carry its cameras, with at least one dynamic camera.

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

**Blank or black renders** — for a video scene, check `view.buffering`: `True` means the data for that time never arrived within the wait, and an all-black frame means nothing had decoded at all. Raise the wait (`view.wait = 30.0`) for a slow disk or a stream. For a static scene, check that the camera frames the geometry — `camera_from_bbox(scene.bbox(), ...)` is the safe default.

**A frame that ignores `view.time`** — the view has `wait=False` and the decoder had not caught up; the loader keeps showing the last good frame while it buffers. `view.buffering` flags exactly that.

**GPU initialization fails** — confirm a Vulkan-capable driver (Windows/Linux) or macOS 11 or later for Metal. Headless Linux still needs a real GPU device and driver.

## Contributing

Contributions are welcome — bug fixes, new examples, platform fixes, documentation.

- **Everything under the MIT part of [LICENSE](LICENSE)** — issues and pull requests both. Fork it, patch it, send it back.
- **The Artifacts** — issues only. They ship prebuilt, thus there is nothing to patch here. Report a bug with steps to reproduce it and we fix it upstream and ship a new build.

By opening a pull request you agree that your contribution is licensed under the MIT License (Part B of [LICENSE](LICENSE)).
