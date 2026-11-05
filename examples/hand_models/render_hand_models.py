#!/usr/bin/env python3
"""Render the hand models of a video into one image."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from graciasdk import HAND_EDGES, GraciaSDK, draw_points
from hand_models import HAND_MODEL_KEYS, close_up, draw_hand_models, hand_model_keys, load_hand_models, poser_for


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("video", type=Path)
    parser.add_argument("--key", choices=HAND_MODEL_KEYS, help="The key of the hand models; the first that the video carries by default.")
    parser.add_argument("--time", type=float, default=0.0, help="Seconds.")
    parser.add_argument("--camera", help="The name of a scene camera; the static camera nearest to the hands by default.")
    parser.add_argument("--wide", action="store_true", help="Show the whole image of the camera; by default the camera turns to frame the hands.")
    parser.add_argument("--hand", action="append", help="A hand to draw, for example hand_0; all hands by default.")
    parser.add_argument("--mesh", action="store_true", help="Also draw the mesh of the hand model.")
    parser.add_argument("--keypoints", action="store_true", help="Also draw the point clouds of the video.")
    parser.add_argument("--size", type=int, default=1024, help="The longer side of the image in pixels.")
    parser.add_argument("--output", type=Path, default=Path("hand_models.png"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sdk = GraciaSDK()
    scene = sdk.load(str(args.video))
    scene.wait_ready()
    keys = hand_model_keys(scene)
    if not keys:
        raise SystemExit(f"{args.video} carries no hand models")
    models = load_hand_models(scene, args.key or keys[0])

    names = args.hand or list(models.hands)
    joints = np.concatenate([models.joints_at(name, args.time) for name in names])
    if np.isnan(joints).all():
        raise SystemExit(f"no data of {', '.join(names)} at {args.time} s")
    if args.camera:
        camera = scene.camera(args.camera)
    else:
        center = np.nanmean(joints, axis=0)
        camera = min((c for c in scene.cameras if not c.is_dynamic),
                     key=lambda c: float(np.linalg.norm(c.at(args.time).camera_transform[3, :3] - center)))
    if args.wide:
        scale = args.size / max(camera.width, camera.height)
        width, height = round(camera.width * scale), round(camera.height * scale)
        setup = camera
    else:
        width, height = args.size, args.size
        setup = close_up(camera.at(args.time), joints)

    view = sdk.view(scene, setup, width, height, time=args.time)
    image = view.color8.copy()
    square, line = max(2, width // 250), max(1, width // 700)
    poser = poser_for(models) if args.mesh else None
    if args.keypoints:
        for _, points in view.points:
            if len(points) == 21:
                draw_points(image, view.camera_setup, points, HAND_EDGES, (1.0, 0.25, 0.25), square, line)
    draw_hand_models(image, view.camera_setup, models, args.time, poser, names, square, line)
    Image.fromarray(image[..., :3]).save(args.output)
    print(f"{args.output}: {models.model['name']} hands {', '.join(names)} at {args.time} s, seen from camera {camera.name}")


if __name__ == "__main__":
    main()
