# Gradio example

Local UI for `graciasdk`: load a scene, frame it from its bounding box or step through the cameras of the capture, switch between RGB, depth, and flow, scrub the timeline for 4DGS video, isolate one segmentation class, draw the point clouds of the file, and read its custom data.

## Run

One command. `uv` selects the wheel that matches your platform and Python out of `wheels/`, pulls in `gradio`, and starts:

```sh
uv run --find-links ../../wheels --with graciasdk --with gradio gradio_app.py
```

Or install it into a venv, and run it yourself:

```sh
uv venv
uv pip install --find-links ../../wheels graciasdk gradio
.venv/Scripts/python gradio_app.py     # macOS/Linux: .venv/bin/python gradio_app.py
```

The app opens a browser on `127.0.0.1`. Set `GRADIO_SERVER_NAME=0.0.0.0` to serve on all interfaces instead. Do that only on a network that you trust.

## Using it

- **Scene** — `.ply`, `.sog` (static) or a 4DGS video. A video scene shows a `T` slider.
- **Scene camera** — shows for every scene. `Bounding box` frames the whole scene. A video that carries the cameras of the capture lists them after it, each with its kind: `static` (one pose) or `dynamic` (one pose for each frame, spread evenly over the track). The label states how many cameras the file carries. Select one to render from it. A dynamic camera follows the `T` slider, and it interpolates between the two poses that the time falls between. Keep `Bounding box` to use the COLMAP cameras or the bounding box instead.
- **COLMAP** — upload `images.bin` *and* `cameras.bin` together to render from the cameras of the reconstruction. If you do not, the app frames the view from the scene bounding box.
- **Mode** — `Flow` and `Flow arrows` show the flow: the move in pixels of each splat on the image at `T` to where the same splat is at `Flow to T`, each seen from the camera at its own time, so a dynamic camera that moves adds flow. The app keeps one `View`, and each mode reads only its own output from it: `color8`, `depth` or `flow`. Only a video whose splats carry ids has flow. For every other scene, the camera box shows `no flow in this scene` and the preview is empty.
- **Flow to T** — a video scene shows this slider. It sets the second time of the flow, on the same scale as `T`. When it is equal to `T`, nothing moves.
- **Flow colors** — the move of the 95th percentile of the moves in the image shows full color, and the camera box states that scale. `Flow` shows the direction of the move as the hue on the Middlebury color wheel: a pixel with no move is white, and a pixel with no splat in both frames is black. `Flow arrows` draws an arrow every 28 pixels of the preview over the RGB image, in the color that `Flow` gives its pixel. The camera box shows the scale and the percentage of the image that has flow.
- **Class** — a video with segmentation lists its classes here. Select one to render that instance in white and every other splat in black, or `All classes` to render the colors. The control stays hidden when the file has no segmentation.
- **Custom data** — a video with custom data lists its keys here, each with the count of its entries (`scene.custom_data_keys()`). `All entries` lists the key and the description of each entry under the preview. Select a key to see its entries in the order of the file, each with its description, its size and its bytes (`scene.custom_data(key)`): as JSON, as text, or as their first 64 bytes in hex, and a picture in a gallery below the list. The control stays hidden when the file has no custom data.
- **Point clouds** — a video with point clouds shows this checkbox. Select it to draw each point cloud over the RGB image at the time of the `T` slider, in its own color. The point clouds also show under `Flow arrows`. A point cloud of 21 points draws as a hand, with its bones.
- **Hand models** — a video with SOMA-X hand models in its custom data lists their key here, `soma_hands`. Select a key to draw the joints of each hand at the time of the `T` slider. See the [hand models example](../hand_models/README.md).
- **Hand mesh** — select it to also draw the mesh of the hand model. SOMA-X needs the model from [its GitHub repository](https://github.com/NVlabs/SOMA-X): add `--with "py-soma-x @ git+https://github.com/NVlabs/SOMA-X@v0.3.4"` to the command.

The app renders at the aspect ratio of the camera, with a longer side of 1536 pixels. The bounding box camera renders square.

A render needs a GPU: Vulkan on Windows/Linux, Metal on macOS.
