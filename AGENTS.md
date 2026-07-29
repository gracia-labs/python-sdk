# AGENTS.md

> Write docs in Simplified Technical English (ASD-STE100): short active sentences, present tense, no gerund verbs, no contractions.

## What this repo is

This is a **distribution repository**: the prebuilt `graciasdk` wheels, the documentation to use them, and an example that runs. There is no source code here, and nothing in this repository compiles.

```
wheels/            prebuilt .whl artifacts, one per (python tag, platform tag)
examples/gradio/   gradio UI exercising the public API
README.md          install + API reference — the only docs users get
```

The wheels are published artifacts. Each wheel carries the compiled extension module with `graciasdk/__init__.py`, the Python wrapper. Treat them as opaque and immutable.

## Rules

- **Never hand-edit or repackage a wheel** — do not unzip, patch, and rezip it, and do not edit `graciasdk/__init__.py` inside it. A new published build replaces a wheel completely, thus a local change is discarded without notice. A hand-edited wheel also has contents that do not match its `RECORD` hashes.
- **You cannot edit the Python API here.** If it must change, the change belongs upstream in the build that produces these wheels. Open an issue, and do not patch it here.
- Wheels are plain git binaries, **not LFS**. `pip install` from a raw GitHub URL must keep working. Do not move them to LFS. Do not add the standard Python `.gitignore` rule for `wheels/` again. The rule was removed on purpose. If you add it again, it drops without notice the artifacts that this repository exists to ship.
- Keep one wheel for each `(python tag, platform tag)`. A publish replaces the wheel that has a matching tag, and it leaves the rest of the matrix alone. Do not delete the wheels of other platforms to "clean up".
- Do not commit `.venv/`, `__pycache__/`, or rendered output from the example.
- When a new wheel changes the API, update `README.md` **in the same change**.

## Verifying a change

Run any change that touches the example or the install instructions. Do not only read it:

```sh
cd examples/gradio
uv run --find-links ../../wheels --with graciasdk --with gradio gradio_app.py
```

`uv` resolves the wheel that matches the host platform and Python straight out of `wheels/`. Thus this is also the fastest check that a new wheel installs and imports. To check the import only, and not launch the UI:

```sh
uv run --find-links ../../wheels --with graciasdk python -c "import graciasdk; print(graciasdk.__all__)"
```

A real render needs a GPU (Vulkan on Windows/Linux, Metal on macOS) and a scene file. `.ply` / `.sog` are static. `.mint` is 4DGS video, and it needs `wait_ready()` before the first frame.

## Conventions

- Code is comment-free by default: no comment that restates what the next line does, and no "added for X" notes. Comment only a constraint that the code cannot express.
- Keep the example dependency-light: `graciasdk` and `gradio`, with the `numpy` that the wheel already pulls in.
