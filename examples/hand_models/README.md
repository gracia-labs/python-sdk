# Hand models example

A video can carry the poses of the SOMA-X hand model as [custom data](../../README.md#custom-data-in-the-scene). This example unpacks them, poses the hand model, and draws the hands over a view.

**The format is a draft.** It can change. The macOS and Linux wheels read custom data. The Windows wheel does not.

- `hand_models.py` — the module: unpack, pose, draw.
- `render_hand_models.py` — a command that renders one image.

The [Gradio example](../gradio/README.md) and the [notebook](../notebooks/video_dynamic_camera.ipynb) also show the hands.

## Run

The joints need no hand model:

```sh
cd examples/hand_models
uv run --find-links ../../wheels --with graciasdk --with pillow render_hand_models.py path/to/video --time 1.5
```

A mesh of SOMA-X needs the model from [its GitHub repository](https://github.com/NVlabs/SOMA-X). It runs on the CPU, and it downloads the assets of the model the first time:

```sh
uv run --find-links ../../wheels --with graciasdk --with pillow --with "py-soma-x @ git+https://github.com/NVlabs/SOMA-X@v0.3.4" render_hand_models.py path/to/video --time 1.5 --mesh
```

By default, the static camera nearest to the hands turns to frame them. `--camera 014` selects a camera, `--wide` shows its whole image, `--hand hand_0` draws one hand, and `--keypoints` also draws the point clouds of the video.

On Linux, the SDK needs the Vulkan loader, the package `libvulkan1`. `Vulkan error -3` tells you that it is not there.

## Use it from Python

```python
from hand_models import draw_hand_models, hand_model_keys, keypoint_track, keypoints_at, load_hand_models, poser_for

models = load_hand_models(scene, hand_model_keys(scene)[0])  # "soma_hands"
models.joints_at("hand_0", 1.5)                              # (21, 3), NaN where a frame has no data
models.chunks[0].hands["hand_0"].shape.bones                 # (24,)

view = sdk.view(scene, camera, 1024, 1024, time=1.5)
image = view.color8.copy()
draw_hand_models(image, view.camera_setup, models, view.time)  # add poser_for(models) to draw the mesh
```

The drawing goes over the splats, and it does not test depth, the same as `draw_points`. A time that no entry covers draws nothing.

### Get the keypoints

Two calls give the 21 keypoints of a hand at a time, in the order of `HAND_EDGES`:

```python
models.joints_at("hand_0", 1.5)                # from the joints field of the entry; needs no hand model

poser = poser_for(models)
keypoints_at(models, poser, "hand_0", 1.5)     # from the hand model, posed with the fields of the entry
poser.keypoints(shape, articulation, rotation, translation)  # the same, for values that you give

times, keypoints = keypoint_track(models, poser, "hand_0")   # (N,) seconds and (N, 21, 3), one for each row of the hand
```

All these calls give NaN where the hand has no data. The keypoints are joints of the model. At a row, the keypoints of the model and the `joints` field are the same, up to the rounding of the numbers. Between two rows, the keypoints of the model and the mesh come from one pose, and `joints_at` can differ from them by a few millimeters in fast motion. When you give a poser, `draw_hand_models` draws the keypoints of the model.

## The format

### Keys and entries

Each chunk of the video that has hands has one entry of custom data:

| Part | Value |
| --- | --- |
| Key | `soma_hands`. |
| Description | Free text, for example `SOMA-X hands, 0.000-1.067 s`. |
| Data | JSON in UTF-8. |

Several entries have the same key. A chunk is a time range of the track. An entry holds all that a reader needs for its chunk, and a reader does not need another entry to use it.

### An entry

```json
{
  "format": "hand_models",
  "version": 1,
  "model": {"name": "soma", "package": "py-soma-x==0.3.4", "assets": "hf://nvidia/soma-x@f81a01796f652260ff930d5318d6c6b845a505ed", "lod": "mid"},
  "begin": 0,
  "end": 1066667,
  "hands": {
    "hand_0": {
      "side": "right",
      "identity": [0.31, -0.42, 0.11],
      "scale": 0.4326,
      "bones": [0.0146, 0.0135, 0.0079],
      "rotation": [[0.1, 2.0, -0.3], [0.1, 2.0, -0.3], null],
      "translation": [[0.006, 0.002, -0.279], [0.006, 0.002, -0.278], null],
      "articulation": [[[0.1, 0.0, 0.2], [0.0, 0.3, 0.1]], [[0.1, 0.0, 0.2], [0.0, 0.3, 0.1]], null],
      "joints": [[[0.006, 0.002, -0.279], [0.01, 0.0, -0.27]], [[0.006, 0.002, -0.278], [0.01, 0.0, -0.27]], null]
    }
  }
}
```

This example shortens `identity`, `bones`, `articulation` and `joints`, and it shows three rows.

| Field | Meaning |
| --- | --- |
| `format`, `version` | `hand_models` and `1`. A reader refuses other values, and it ignores fields that it does not know. |
| `model.name` | `soma`. |
| `model.package`, `model.lod` | The release of the model, and the level of detail of its mesh. `py-soma-x==0.3.4` is the tag `v0.3.4` of the repository. |
| `model.assets` | The assets of the model on Hugging Face, with their revision. |
| `begin`, `end` | The time range of the chunk, in microseconds of the track. |
| `hands` | The hands of this chunk by name. The name is the name of the instance and of the point cloud of the same hand, for example `hand_0`. |

These fields of a hand stay the same over the chunk:

| Field | Size | Meaning |
| --- | --- | --- |
| `side` | | `left` or `right`. |
| `identity` | 20 | The shape coefficients of the model. |
| `scale` | 1 | Scene units for each meter. |
| `bones` | 24 | The length of each bone of the model in scene units, in the order of `articulation`: from each finger joint to its parent. A reader with no hand model can read them here. |
| `bone_scales` | 24 | Optional: the scale of each bone length of the model, joints 1 to 24 in the order of `articulation`, 1 for no change. `SomaPoser` gives them to the model with the identity. |

These fields of a hand have one row for each sample of the chunk:

| Field | Size | Meaning | Between two rows |
| --- | --- | --- | --- |
| `rotation` | `R` × 3 | Axis-angle: the rotation of the wrist frame of the model in the scene. | It turns along the shortest arc. |
| `translation` | `R` × 3 | The wrist joint in the scene. | It moves along a line. |
| `articulation` | `R` × 24 × 3 | The axis-angle of each finger joint, relative to the bind pose of the model. | Each joint turns along the shortest arc. |
| `joints` | `R` × 21 × 3 | The joints in the scene, in the order of the hand keypoints and `HAND_EDGES`. A reader with no hand model can draw them. | The wrist moves along a line, and each bone turns along the shortest arc. |

### Rows and time

The rows spread evenly from `begin` to `end`, and they include both ends. Row `i` is at `begin + i * (end - begin) / (R - 1)`. The entry states no frame rate and no frame numbers.

The last row of a chunk and the first row of the next chunk have the same time. The later chunk holds that time. Thus a hand can change at once at the start of a chunk: two chunks can hold different values for the same time, and a reader does not blend them.

`null` marks a row with no data. A time next to a `null` row has no data. A hand that an entry does not name has no data in that chunk.

To get the mesh at a time, interpolate the fields of the two rows, then pose the model. To get the joints with no hand model, interpolate `joints`. In the two cases the bones keep their lengths. If each joint of `joints` moves along a line, the bones get shorter between two rows.

### Pose the model

A point `x` of the posed model, in meters, goes into the scene with:

```text
scale * R(rotation) @ x + translation
```

The wrist of the model is at the origin of `x`. The scene is the space of the splats of the video. No other transform applies.

The model does all these steps. `SomaPoser` in `hand_models.py` makes these calls to [SOMA-X](https://github.com/NVlabs/SOMA-X):

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
