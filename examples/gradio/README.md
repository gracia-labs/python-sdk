# Gradio example

Local UI for `graciasdk`: load a scene, frame it from its bounding box or step through the cameras of the capture, switch between RGB, depth, and mesh, scrub the timeline for 4DGS video, and isolate one segmentation class.

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

- **Scene** — `.ply`, `.sog` (static) or `.mint` (4DGS video). A video scene shows a `T` slider.
- **Scene camera** — a `.mint` video that carries the cameras of the capture lists them here, each with its kind: `static` (one pose) or `dynamic` (one pose for each frame). Select one to render from it. A dynamic camera follows the `T` slider, and it interpolates between the two poses that the time falls between. **Camera fps** sets the frame rate that maps the time to a pose, and it shows only when the file has a dynamic camera. Keep `Off` to use the COLMAP cameras or the bounding box instead.
- **COLMAP** — upload `images.bin` *and* `cameras.bin` together to render from the cameras of the reconstruction. If you do not, the app frames the view from the scene bounding box.
- **Mode** — the app populates `Mesh` only for video scenes that carry mesh data.
- **Class** — a `.mint` video with segmentation lists its classes here. Select one to render only the splats of that instance, or `All classes` to render the full scene. The control stays hidden when the file has no segmentation.

The app renders square, because the render size is fixed when it starts. A camera has the aspect ratio of its source image, thus the preview resizes to that aspect ratio to stay free of distortion.

A render needs a GPU: Vulkan on Windows/Linux, Metal on macOS.
