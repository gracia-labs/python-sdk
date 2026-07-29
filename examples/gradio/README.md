# Gradio example

Local UI for `graciasdk`: load a scene, frame it from its bounding box or step through COLMAP cameras, switch between RGB, depth, and mesh, and scrub the timeline for 4DGS video.

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
- **COLMAP** — upload `images.bin` *and* `cameras.bin` together to render from the cameras of the reconstruction. If you do not, the app frames the view from the scene bounding box.
- **Mode** — the app populates `Mesh` only for video scenes that carry mesh data.

A render needs a GPU: Vulkan on Windows/Linux, Metal on macOS.
