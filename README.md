# Gracia Python SDK

Python bindings for the Gracia Gaussian-splat renderer. The renderer supports 3DGS (static) and 4DGS (video). The SDK renders on the GPU and returns the result as NumPy arrays.

This repository ships **prebuilt wheels**. There is nothing to compile.

```
wheels/              prebuilt graciasdk wheels, one per platform
examples/gradio/     local UI: load a scene, pick a camera, preview RGB/depth/flow
examples/notebooks/  a video tutorial: RGB and depth videos, instance overlay, keypoint confidence, hand models
```

## Requirements

- CPython 3.12 or newer — one wheel for each platform covers every version
- A standard interpreter with the GIL enabled — **the SDK does not support free-threaded builds (`3.13t`, `3.14t`, …)**
- GPU and driver: Vulkan on Windows/Linux, Metal on macOS 14 or later (Apple silicon only — the SDK does not support Intel Macs)
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
| macOS Apple Silicon | `cp312-abi3-macosx_14_0_arm64` |
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
| any other | video 4DGS; such a file can also carry the cameras of the capture, the instance labels and series, as the points of a hand |

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

The wait is 5 seconds for each scene by default. `sdk.view(..., wait=10.0)` sets it, and `wait=False` skips it. A read never raises when the data is not there after the wait, also with `wait=False`: `view.buffering` becomes `True`, which means that an output is *not* the time that you asked for. It shows an earlier time, or nothing if nothing had decoded yet. A static scene is never buffering.

A view first waits for the **first** frame of a video (30 s timeout), and it raises `RuntimeError` when that times out, and at once, with the reason, for a file that the video refuses: a file that it does not play, that needs a newer player, or that holds a head hash. `scene.wait_ready()`, `scene.ready()`, `scene.wait_buffered(timeout=5.0)` and `scene.is_buffering()` give the same signals without a view. `scene.bbox()` and `scene.adaptive_bbox()` wait for ready themselves, thus they can block too.

A video takes a time to the nearest microsecond. A frame can fall between two microseconds, and the microsecond nearest a frame shows that frame: thus `k / fps` shows frame `k`. A time before 0 shows 0, and a time at or past the end of a video shows its last microsecond. A view and `scene.attributes` hold the time so; `scene.set_time` holds the end only once the video knows its `duration()`.

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

A view takes a `SceneCamera` as it is and uses it at `view.time`, thus the camera and the frame stay together. The view moves the camera with the scene and with the track of the video, as their splats move, thus the render shows what the camera recorded. `cam.at(time)` gives the `CameraSetup` for a time in seconds, in the coordinates of the video, as the rows and the series are. A view takes a `CameraSetup` in the coordinates of the world.

- A **static** camera holds one pose. It ignores the time.
- A **dynamic** camera holds a pose at each of its times, `cam.times` in seconds. Between two poses the position moves along a straight line and the rotation along the shorter arc. A time where the video states no pose, or a pose that is not finite, takes the finite pose nearest in time. `cam.qvecs` and `cam.tvecs` keep a pose that is not finite as NaN.

The projection comes from the COLMAP intrinsics of the source image. Thus render at the aspect ratio of `cam.width / cam.height` for an image with no distortion.

A static scene and a video with no camera data report `scene.cameras` as empty. A camera that states no pose, as a camera whose path the cut of an edit leaves empty, is not in `scene.cameras`.

## Instances in the scene

A 4DGS video can label each splat with the segmentation instance that it belongs to. `scene.instance_names()` gives the name of each instance by id, and `instance_filter` renders one of them as a mask:

```python
scene.instance_names()                    # {1: "knife_0", 2: "knife_1", …}
scene.set_uint("instance_filter", 1)      # instance 1 in white, every other splat in black
mask = view.color8[..., 0]
scene.set_uint("instance_filter", 0)      # the colors again
```

Every splat still takes part in visibility, thus an object in front of the instance hides it in the mask. A static scene and a video with no segmentation report no instance names, and the filter does not change them.

## Series in the scene

A video's track can carry series: data over time, for example the points of the hands of the capture. A series has a name, attributes that it samples at times, and values of its own. Its samples come in chunks, and a time that no chunk plays has no data. The scene reads the list of the series from the file when you first use it.

```python
hand = next(s for s in scene.series if s.name == "hand_0")
hand.index, hand.attributes               # 0, (("positions", "F32", (21, 3), "Linear"),)
hand.at(1.5)["positions"]                 # (21, 3) float32 at the frame of 1.5 s; None where no chunk plays it
hand.at()                                 # each attribute at the frame that the video shows now
chunk = hand.samples()[0]
chunk.times, chunk.attributes["positions"]   # (S,) seconds and (S, 21, 3), NaN where a sample has no data

image = view.draw_series()                # view.color8 with the hand of each series at view.time
```

`series.at(time)` seeks the video to the time and waits for its data, as `scene.attributes(time)` does. The video loads the series with its splats, thus the call gives each attribute at the frame that the video shows, and the points and the splats are of one frame. `series.at()` with no time reads the frame that the video shows now, with no seek and no wait. A `wait` of `False` reads what has decoded, and `None` comes also where the data of the time did not come. `series.at(time)` gives each attribute by its interpolation. A `"Linear"` value moves along a line between the two samples around the time. A `"Rotation"`, unit quaternions `(x, y, z, w)`, turns along the shorter arc. A `"Step"` holds the sample before the time, and a `"Constant"` is one value for its whole chunk. A NaN is a value that a sample does not have, thus a point with no data in either sample is NaN.

`view.draw_series(image=None)` draws the hands of the series over a copy of `view.color8`, or into `image` in place. Each series of `scene.hand_keypoints`, a series of an OpenPose hand with its 21 `positions` ([The series of the hands](#the-series-of-the-hands)), draws as a hand with the bones of `HAND_EDGES`, and any other series draws nothing. Each hand lands on its splats, also where the track or the scene moves and from a camera in the coordinates of the world. Series `k` of a scene takes the color `SERIES_COLORS[k % 6]`. The size of the squares and of the lines follows the width of the image.

`draw_points(image, camera, points, edges)` draws other points, in the coordinates of the world. It projects the points with the camera. It draws a square at each point and a line for each edge `(a, b)` into the image, in place. The image is a float image in `[0, 1]` or an 8-bit image, with 3 or 4 channels. A NaN point, or a point behind the camera, draws nothing. The drawing goes over the splats, and it does not test depth. `HAND_EDGES` is the 20 bones between the 21 keypoints of a hand.

A video can carry the poses of the SOMA-X hand model, as the series `soma_hands/hand_0`, and the confidence of the keypoints of its hands, as `hand_keypoint_confidence/hand_0`: see [Hands in the scene](#hands-in-the-scene).

A static scene and a video with no series report `scene.series` as empty.

## Hands in the scene

A video can carry the poses of the SOMA-X hand model of each hand, and how well the cameras saw each keypoint of a hand, each as a series of the hand ([The series of the hands](#the-series-of-the-hands)). **The series are drafts.** They can change.

```python
models = scene.hand_models                      # None when the video carries none
models.hands                                    # ("hand_0", "hand_1")
models.joints_at("hand_0", 1.5)                 # (21, 3), NaN where the hand has no data
pose = models.pose_at("hand_0", 1.5)            # HandPose, None where the hand has no data
pose.shape.side, pose.shape.bones               # "right", (24,)

image = view.draw_hands()                       # view.color8 with the joints of each hand at view.time
image = view.draw_hands(mesh=True)              # the mesh and the keypoints of the hand model in place of the joints
```

`view.draw_hands(image=None, mesh=False, hands=None)` draws over a copy of `view.color8`, or into `image` in place. Each hand draws its joints and the bones of `HAND_EDGES` in yellow. With `mesh`, it draws the shaded mesh of the posed model, and the keypoints of the model in place of the joints. `hands` names the hands to draw, each hand by default. Each hand lands on its splats, also where the track or the scene moves and from a camera in the coordinates of the world. The drawing goes over the splats, and it does not test depth, the same as `draw_points`. A time that no chunk of a hand plays draws nothing of that hand.

A mesh and the keypoints of the model need SOMA-X from [its GitHub repository](https://github.com/NVlabs/SOMA-X) and Pillow. The model runs on the CPU, and it downloads its assets the first time:

```sh
uv run --find-links wheels --with graciasdk --with pillow --with "py-soma-x @ git+https://github.com/NVlabs/SOMA-X@v0.3.4" your_script.py
```

### Get the keypoints

Two calls give the 21 keypoints of a hand at a time, in the order of `HAND_EDGES`:

```python
models.joints_at("hand_0", 1.5)                 # from the joints of the series; needs no hand model
models.keypoints_at("hand_0", 1.5)              # from the hand model, posed with the attributes of the series
models.poser.keypoints(pose)                    # the same, for a pose that you give
times, keypoints = models.keypoint_track("hand_0")   # (N,) seconds and (N, 21, 3), one for each sample of the hand
vertices, faces = models.mesh_at("hand_0", 1.5)      # (V, 3) and (T, 3); None where the hand has no data
```

All these calls give NaN, or `None`, where the hand has no data. Each value is in the coordinates of the video, as the series are. The keypoints are joints of the model. At a sample, the keypoints of the model and the `joints` attribute are the same, up to the rounding of the numbers. Between two samples, the keypoints of the model and the mesh come from one pose, and `joints_at` can differ from them by a few millimeters in fast motion, as each joint moves along a line. `models.poser` makes the model at its first use. `draw_mesh(image, camera, vertices, faces)` draws a mesh of the world as `draw_points` draws points.

### Get the keypoint confidence

The series of the points of the hands hold their keypoints. A video can also carry how well the cameras saw each keypoint:

```python
from graciasdk import FINGERTIPS, hand_confidence

confidence = scene.keypoint_confidence          # None when the video carries none
confidence.at("hand_0", 1.5)                    # (21,) at 1.5 s, in the order of HAND_EDGES

points = next(s for s in scene.series if s.name == "hand_0")
times = np.concatenate([chunk.times for chunk in points.samples()])
values = confidence.at_times("hand_0", times)   # (S, 21), one row for each sample of the points

hand_confidence(confidence.at("hand_0", 1.5))   # one number for the hand: the mean of its 21 values
hand_confidence(values, "min")                  # (F,): the weakest keypoint of each frame
hand_confidence(values[:, FINGERTIPS], "seen")  # (F,): the share of the fingertips that the cameras saw
```

A value is from 0 to 1. 0 is a keypoint that no camera saw, and a higher value is a keypoint that the cameras saw better. The values rank the keypoints; they are not probabilities. The confidence is about the cameras, not about the points. A point can have a position and 0, and a keypoint above 0 can have no position. `at` and `at_times` give NaN where the video has no confidence of the hand. A video that carries no confidence, for example one made before this format, gives `None`, and it reads as before in all other ways.

`hand_confidence` aggregates the keypoints, the last axis of the values, into one confidence of the hand: the `mean` (the default), `median`, `min` or `max` of the values, or `seen`, the share of the values above 0. A keypoint that no camera saw counts as 0, thus `mean` is `seen` times the mean of the keypoints that the cameras saw, and `min` is 0 when any keypoint is unseen. A row with NaN gives NaN. Select keypoints, as with `FINGERTIPS`, to aggregate them alone, and use NumPy on the values for any other aggregate.

### The series of the hands

Each hand of the video can have a series of its 21 keypoints, an OpenPose hand. Its values state `format` `openpose_hand`, and its attribute `positions` holds float32 `(21, 3)` for each sample in the scene, in the order of `HAND_EDGES`: the wrist, then four joints of each finger from the thumb to the little finger. Between two samples each keypoint moves along a line, `"Linear"`, and NaN marks a keypoint with no data. The name of the series is the name of the hand, for example `hand_0`.

Each hand of the video that has hand models has one series. Its name is `soma_hands/` and the name of the hand, for example `soma_hands/hand_0`. The name of the hand is the name of the instance and of the series of the points of the same hand.

The values of the series:

| Value | Meaning |
| --- | --- |
| `format`, `version` | `hand_models` and `2`. A reader refuses other values, and it ignores values that it does not know. |
| `model.name` | `soma`. |
| `model.package`, `model.lod` | The release of the model, and the level of detail of its mesh. `py-soma-x==0.3.4` is the tag `v0.3.4` of the repository. |
| `model.assets` | The assets of the model on Hugging Face, with their revision. |
| `side` | `left` or `right`. |

Each chunk holds these attributes of one value for the whole chunk, `"Constant"`:

| Attribute | Shape | Meaning |
| --- | --- | --- |
| `identity` | 20 | The shape coefficients of the model. |
| `scale` | 1 | Scene units for each meter. |
| `bones` | 24 | The length of each bone of the model in scene units, in the order of `articulation`: from each finger joint to its parent. A reader with no hand model can read them here. |
| `bone_scales` | 24 | Optional, in each chunk of a series or in none: the scale of each bone length of the model, joints 1 to 24 in the order of `articulation`, 1 for no change. The poser gives them to the model with the identity. |

Each chunk holds these attributes for each sample, float32:

| Attribute | Shape | Meaning | Between two samples |
| --- | --- | --- | --- |
| `rotation` | 4 | A unit quaternion `(x, y, z, w)`: the rotation of the wrist frame of the model in the scene. | `"Rotation"`: it turns along the shorter arc. |
| `translation` | 3 | The wrist joint in the scene. | `"Linear"`: it moves along a line. |
| `articulation` | 24 × 4 | A unit quaternion for each finger joint, relative to the bind pose of the model. | `"Rotation"`: each joint turns along the shorter arc. |
| `joints` | 21 × 3 | The joints in the scene, in the order of the hand keypoints and `HAND_EDGES`. A reader with no hand model can draw them. | `"Linear"`: each joint moves along a line. |

Each chunk of the capture has one chunk of each hand. Its samples spread evenly from the start of the chunk to its end, both included. The series states no frame rate and no frame numbers. The last sample of a chunk and the first sample of the next chunk have the same time. The later chunk holds that time. Thus a hand can change at once at the start of a chunk: two chunks can hold different values for the same time, and a reader does not blend them. NaN marks a sample with no data, and a time next to it has no data. A chunk with no sample of the hand is not there: that time has no data of the hand.

A point `x` of the posed model, in meters, goes into the scene with `scale * R(rotation) @ x + translation`. The wrist of the model is at the origin of `x`. The scene is the space of the splats of the video. SOMA-X takes axis angles: `pose_at` turns each quaternion into one. The poser makes these calls to [SOMA-X](https://github.com/NVlabs/SOMA-X):

```python
import torch
from soma import SOMAHandLayer
from soma.assets import get_assets_dir

layer = SOMAHandLayer(data_root=get_assets_dir(revision=revision), hand_type=side, device="cpu", mode="torch", lod=lod, correctives_model_path=None)
layer.prepare_identity(identity[None], bone_scales, global_scale=scale)  # bone_scales is (1, 24) or None
output = layer.pose(torch.cat((rotation[None], articulation))[None],     # (1, 25, 3): the wrist comes first
                    global_translation=translation[None],                # (1, 3)
                    reference_pose=layer.bind_pose_world[:, :3, :3])     # the rotations are relative to the bind pose
output.vertices, output.joints                                           # (1, V, 3) and (1, 25, 3), in scene units
```

`revision` is the part of `model.assets` after `@`. The poses use no pose correctives: the model applies them only with `apply_correctives=True`, thus it does not load them.

Each hand of the video that has keypoint confidence has one series. Its name is `hand_keypoint_confidence/` and the name of the hand, for example `hand_keypoint_confidence/hand_0`, and the name of the hand is that of the series of its points. Its values are `format` `hand_keypoint_confidence` and `version` `2`, and a reader refuses other values. Its one attribute is `confidence`, float32 with 21 values in the order of the points of the hand and `HAND_EDGES`, from 0 to 1, `"Linear"`. Its samples and its time are those of the hand models, and a sample and the sample of the points of the hand at its time hold the same instant.

## Custom data in the scene

A video's file and its track can each carry values, as JSON gives them. The track can also carry blobs of any bytes, each with a key and a description. Several blobs can have the same key. `scene.video_values` gives the values of the file and `scene.values` those of the track. `scene.blobs` lists each blob in the order of the file, and `scene.blob(index)` gives its bytes:

```python
scene.video_values                        # {"take": 3, …}
scene.values                              # {"rig": "R2", …}
scene.blobs                               # (Blob(index=0, key="rig", description="the capture rig as JSON", size=812), …)
rig = json.loads(scene.blob(0))
```

The scene reads the file at each call: `values`, `video_values` and `blobs` read its head alone, and `blob` also the bytes of one blob. A video with no custom data gives `{}` and `()`, and so does a static scene. `scene.blob` raises `IndexError` past the last blob.

## Splat attributes in the scene

`scene.attributes(time)` gives the raw floats of each splat of a video at a time: the values that the GPU decodes, before a render. It renders nothing, and a render reads no attributes.

```python
a = scene.attributes(1.5)                                  # every field
a.position.shape, a.sh.shape                               # (N, 3), (N, 45)
a = scene.attributes(1.5, fields=("position", "opacity"))  # only these; the other fields are None
np.savez("splats_1.5s.npz", position=a.position, opacity=a.opacity)
```

- The rows are the splats that live at the time, in the order of the video. Their count changes with the time.
- Each value is in the coordinates of the video, before `scene.set_transform` and before a transform of its track.
- The call seeks the video and waits for the data of the time, as a view with the same `wait` does. When the data does not come, `a.buffering` is `True`.
- `sh` takes 45 floats a splat, 15 times as much as `position`: ask only for the fields that you need.
- A static scene and a video in the `.mint` format raise `ValueError`, and so does a name that is not a field of `SplatAttributes`. The SDK reads the format of a file from its bytes, not from its name.

## API

**`GraciaSDK(max_splats_count=16_000_000)`**
- `.load(path) -> Scene`
- `.view(scene | [scenes], camera, width, height, time=0.0, model_transform=None, wait=True) -> View` — `camera` is a `CameraSetup` in the coordinates of the world, or a `SceneCamera`, which the view moves with its scene and its track; `wait` is the seconds to wait for the data of a video's time (`True` = 5 s, `False` = no wait)

**`View`** — every output renders when you first read it, and stays until a field or a scene changes
- `.scenes`, `.camera`, `.width`, `.height`, `.time`, `.model_transform`, `.wait` — set one to change the view
- `.color` — RGBA `float16` `(H, W, 4)`, values in `[0, 1]`
- `.color8` — RGBA `uint8` `(H, W, 4)`, `.color` rounded to bytes
- `.depth` — `float32` `(H, W)`, raw view-space Z (unnormalized, negative in front of the camera); `0` where nothing was hit. Normalize it yourself for display.
- `.coverage` — `float32` `(H, W)` in `[0, 1]`, the accumulated opacity of the splats; it renders with `.depth`
- `.flow(reference_time) -> FlowResult | None` — the flow from `.time` to `reference_time`; `None` when no scene has flow. See [Flow](#flow)
- `.series -> ((Series, {name: array} | None), …)` — each series of the scenes with its attributes at `.time`
- `.draw_series(image=None) -> image` — the hand of each series of `scene.hand_keypoints` at `.time` over a copy of `.color8`, or into `image` in place; see [Series](#series-in-the-scene)
- `.draw_hands(image=None, mesh=False, hands=None) -> image` — the SOMA-X hands at `.time` the same way; see [Hands](#hands-in-the-scene)
- `.camera_setup -> CameraSetup` — the camera at `.time`; for a `SceneCamera`, in the coordinates of the video, as `cam.at(.time)` gives it
- `.buffering` — an output since the last change is not the time that was asked for (video only; see [Video](#video-4dgs))

The arrays of a view belong to the view: copy an array before you draw into it.

**`Scene`**
- `.bbox() -> (min_x, min_y, min_z, max_x, max_y, max_z)` — for a video it waits for the stream to be ready, thus it can block
- `.adaptive_bbox()` — the same, with the outliers discounted
- `.count() -> int` — splat count. For a video it is the frame drawn last: `0` before the first render
- `.set_transform(m)` — 4×4 model matrix
- `.set_flag(key, value)` — `"sh3"` for the view-dependent color, `"mip"` for the antialiasing filter. A video and a `.guf` scene load with `"mip"` on, and a `.ply` or `.sog` scene with it off; a track of a video that states the `Mip` option draws by it until `"mip"` is set
- `.set_uint(key, value)` — `"instance_filter"`: the id of the instance to render as a mask, `0` for the colors
- `.instance_names() -> {id: name}` — the instances that a video labels its splats with
- `.is_video`, `.duration()`, `.set_time(t)`, `.wait_ready(timeout=30.0)`, `.ready()`
- `.is_buffering() -> bool` — the current time has no data yet (video only)
- `.wait_buffered(timeout=5.0) -> bool` — block while it buffers; `False` on timeout, never raises
- `.cameras -> (SceneCamera, …)` — the cameras that the file carries, sorted by name
- `.camera_kinds -> ("static" | "dynamic", …)` — one for each camera, in the same order
- `.camera(name | index) -> SceneCamera`
- `.series -> (Series, …)` — the series that the file carries, in the order of the file. A series keeps no scene alive: a read of a series whose scene is gone raises `ReferenceError`
- `.hand_keypoints -> (Series, …)` — the series of the OpenPose hands that the video carries
- `.hand_models -> HandModels | None` — the SOMA-X hands that the video carries
- `.keypoint_confidence -> KeypointConfidence | None` — how well the cameras saw each keypoint of the hands
- `.values -> dict` — the values of the custom data of the track
- `.video_values -> dict` — the values of the custom data of the file
- `.blobs -> (Blob, …)` — each blob of the custom data of the track, in the order of the file
- `.blob(index) -> bytes` — the bytes of one blob of `.blobs`
- `.attributes(time, fields=None, wait=True) -> SplatAttributes` — the splats of a video at `time` as it decodes them, with no render; see [Splat attributes](#splat-attributes-in-the-scene)

**`SplatAttributes`** — one row for each splat that lives at the time; a field that the call does not ask for is `None`
- `.position` — `float32` `(N, 3)`
- `.scale` — `float32` `(N, 3)`, linear
- `.rotation` — `float32` `(N, 4)`, a unit quaternion `(w, x, y, z)`
- `.opacity` — `float32` `(N,)` in `[0, 1]`
- `.color` — `float32` `(N, 3)`, the color of band 0: `0.5 + C0 * f_dc`
- `.sh` — `float32` `(N, 45)`, the coefficients 1 to 15 of red, then green, then blue, as `f_rest` of a 3DGS PLY; `0` where the video has no bands 1 to 3
- `.instance` — `uint16` `(N,)`, the instance id of each splat: `0xFFFF` for no instance, `0` where the video labels none
- `.buffering` — the video had no data for the time: the rows are of an earlier time, or every field is `None`

**`SceneCamera`**
- `.at(time=0.0) -> CameraSetup` — the camera to render with at that time
- `.name`, `.kind`, `.is_dynamic`, `.poses_count`
- `.width`, `.height`, `.model`, `.pinhole` — source image size and intrinsics `(fx, fy, cx, cy)`
- `.qvecs`, `.tvecs` — the COLMAP world-to-camera poses, `(N, 4)` and `(N, 3)` `float32`
- `.times` — `(N,)` `float64` seconds of each pose of a dynamic camera; empty for a static camera

**`Series`**
- `.at(time=None, wait=True) -> {name: array} | None` — each attribute at the frame of that time, or of the frame that the video shows with no time; `None` where no chunk plays it, or the data of the time did not come
- `.samples() -> (SeriesChunk, …)` — the samples of each chunk, read from the file at each call
- `.index` — the place of the series in `scene.series`, and its color in `view.draw_series`
- `.name`, `.values` — the values of the series as a `dict`
- `.attributes` — `(name, dtype, shape, interpolation)` of each attribute, the shape of one value
- `.chunks` — `(begin, end)` seconds of each chunk

**`SeriesChunk`**
- `.begin`, `.end` — the seconds where the chunk starts and stops to play
- `.times` — `(S,)` `float64` seconds of each sample
- `.attributes` — each attribute by name: `(S, …)`, or the one value of a `"Constant"`

**`HandModels`** — see [Hands in the scene](#hands-in-the-scene)
- `.hands`, `.model`, `.series` — the names of the hands, the model as the values state it, and the series of each hand
- `.joints_at(hand, time) -> (21, 3)`, `.pose_at(hand, time) -> HandPose | None`, `.times(hand) -> (N,)`
- `.keypoints_at(hand, time) -> (21, 3)`, `.mesh_at(hand, time) -> (vertices, faces) | None`, `.keypoint_track(hand) -> (times, keypoints)` — they need SOMA-X
- `.poser -> SomaPoser` — `.keypoints(pose)`, `.mesh(pose)` and `.faces(side)` of the model

**`HandPose`** — `.shape` (`HandShape`: `.side`, `.identity`, `.scale`, `.bones`, `.bone_scales`), `.articulation` `(24, 3)`, `.rotation` `(3,)` and `.translation` `(3,)`, each rotation an axis angle

**`KeypointConfidence`** — `.hands`, `.series`, `.at(hand, time) -> (21,)`, `.at_times(hand, times) -> (N, 21)`

**`hand_confidence(values, aggregate="mean")`** — one confidence of a hand from the last axis of `values`, by one of `CONFIDENCE_AGGREGATES`; `FINGERTIPS` is the keypoints of the tips of the fingers

**`Blob`**
- `.index` — the place of the blob in `scene.blobs`, which `scene.blob` takes
- `.key`, `.description` — several blobs can share a key
- `.size` — the count of its bytes in the file

**`draw_points(image, camera, points, edges=(), color=(1.0, 0.25, 0.25), square=6, line=2) -> image`** — draw squares at the points and lines along the edges, in place; `HAND_EDGES` is the edges of a hand, and `SERIES_COLORS` the colors of `view.draw_series`

**`draw_mesh(image, camera, vertices, faces, color=(0.35, 0.67, 0.92), opacity=0.6) -> image`** — draw a shaded mesh of the world over the image, in place, with no depth test; it needs Pillow

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

The flow of a pixel is the mean move of the splats on it, weighted by what each splat adds to the color. A move goes from where a splat is at `view.time`, seen from the camera at `view.time`, to where it is at `reference_time`, seen from the camera at `reference_time`. Each place takes the transform of the track at its own time. Thus a track that its file moves along a path adds flow, and so does a dynamic camera that moves: a static table moves in the image when the camera moves. `x` points right and `y` points down the image rows, so a pixel `(x, y)` moves to `(x + flow[..., 0], y + flow[..., 1])`. Only a splat at both times adds to the flow, and `.coverage` is the opacity of those splats. A pixel with `.coverage` below `1/255` gets flow `0`. Only a video whose splats carry ids has flow. For every other scene, `flow` gives `None`.

```python
from graciasdk import draw_flow_arrows, flow_colors

view.time = 1.0
flow = view.flow(1.2)
colors, scale = flow_colors(flow.flow, flow.coverage)           # (H, W, 3) uint8
arrows = draw_flow_arrows(view.color8.copy(), flow.flow, flow.coverage, colors)
```

## Example

`examples/gradio` is a local UI. Load a scene, frame it from its bounding box, from the cameras a video carries or from COLMAP cameras, switch between RGB, depth, and flow, scrub the timeline for 4DGS, isolate one instance, draw the points of its series and its SOMA-X hands, and save the raw floats of the splats at a time. See its [README](examples/gradio/README.md). One command:

```sh
cd examples/gradio
uv run --find-links ../../wheels --with graciasdk --with gradio gradio_app.py
```

### RGB, depth, and instance notebook

[`examples/notebooks/video_dynamic_camera.ipynb`](examples/notebooks/video_dynamic_camera.ipynb) is a complete video rendering tutorial. It selects an embedded dynamic camera with a reproducible random seed. It renders the first 30 RGB and depth frames, writes H.264 videos, and displays both videos in the notebook. It then renders every embedded instance ID at time 0 and draws the visible masks over RGB. When the video carries the confidence of the hand keypoints, it plots the confidence over time and draws the keypoints by their confidence. It does not read an external `cameras.json` file.

The companion [`requirements.txt`](examples/notebooks/requirements.txt) lists every direct dependency. Run the notebook from the repository root:

```sh
uv run --isolated --no-project --python 3.12 \
  --find-links wheels \
  --with-requirements examples/notebooks/requirements.txt \
  jupyter lab examples/notebooks/video_dynamic_camera.ipynb
```

Set `VIDEO_PATH` in the **Settings** cell before the first run. The video must carry its cameras, with at least one dynamic camera, and the series of its SOMA-X hand models.

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

**GPU initialization fails** — confirm a Vulkan-capable driver (Windows/Linux) or macOS 14 or later for Metal. Headless Linux still needs a real GPU device and driver.

## Contributing

Contributions are welcome — bug fixes, new examples, platform fixes, documentation.

- **Everything under the MIT part of [LICENSE](LICENSE)** — issues and pull requests both. Fork it, patch it, send it back.
- **The Artifacts** — issues only. They ship prebuilt, thus there is nothing to patch here. Report a bug with steps to reproduce it and we fix it upstream and ship a new build.

By opening a pull request you agree that your contribution is licensed under the MIT License (Part B of [LICENSE](LICENSE)).
