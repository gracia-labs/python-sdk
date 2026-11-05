"""Read the SOMA-X hands of a video from its custom data, pose them, and draw them over a view.

The README of this folder describes the format. The stored joints need only this module. A mesh and the keypoints of the
model also need SOMA-X from https://github.com/NVlabs/SOMA-X.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw

from graciasdk import HAND_EDGES, CameraSetup, Scene, draw_points, look_at, make_camera, perspective

HAND_MODEL_KEYS = ("soma_hands",)
MESH_COLOR = (0.35, 0.67, 0.92)
JOINT_COLOR = (1.0, 0.85, 0.1)
_FORMAT = "hand_models"
_VERSION = 1
_FINGER_JOINTS = 24
_KEYPOINTS = 21
_SOMA_KEYPOINTS = [0, 1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 16, 17, 18, 19, 21, 22, 23, 24]


@dataclass(frozen=True)
class HandShape:
    """What stays fixed over one chunk: the side, the identity coefficients, the scene units for each meter, the bone lengths in scene units, and SOMA-X's bone-length scales of joints 1-24 when the entry has them."""
    side: str
    identity: np.ndarray
    scale: float
    bones: np.ndarray
    bone_scales: np.ndarray | None = None


@dataclass(frozen=True)
class HandRows:
    """One hand over one chunk. The rows spread evenly from the begin to the end of the chunk, both included. A row with no data holds NaN.

    `rotation` and `translation` are ``(R, 3)``, `articulation` is ``(R, J, 3)`` and `joints` is ``(R, 21, 3)``.
    """
    shape: HandShape
    rotation: np.ndarray
    translation: np.ndarray
    articulation: np.ndarray
    joints: np.ndarray


@dataclass(frozen=True)
class HandChunk:
    """One chunk of the video, from `begin` to `end` in microseconds of the track: its hands by name."""
    begin: int
    end: int
    hands: dict[str, HandRows]


@dataclass(frozen=True)
class HandModels:
    """The hands of one key: the `chunks` in the order of time, and the names of their `hands`."""
    model: dict
    chunks: tuple[HandChunk, ...]
    hands: tuple[str, ...]

    def rows_at(self, hand: str, time: float) -> tuple[HandRows, int, int, float] | None:
        """The rows of a hand at a time in seconds, the two rows around the time, and how far between them; ``None`` for a time with no rows of the hand."""
        micro = time * 1e6
        chunk = next((chunk for chunk in reversed(self.chunks) if chunk.begin <= micro + 0.5), None)
        if chunk is None or micro > chunk.end + 0.5 or hand not in chunk.hands:
            return None
        rows = chunk.hands[hand]
        place = (micro - chunk.begin) / (chunk.end - chunk.begin) * (len(rows.rotation) - 1)
        if abs(place - round(place)) < 1e-3:
            return rows, round(place), round(place), 0.0
        return rows, int(place), int(place) + 1, place - int(place)

    def joints_at(self, hand: str, time: float) -> np.ndarray:
        """The ``(21, 3)`` stored joints at a time, in the order of `HAND_EDGES`, NaN with no data. Between two rows the bones turn and keep their lengths."""
        found = self.rows_at(hand, time)
        if found is None:
            return np.full((_KEYPOINTS, 3), np.nan, dtype=np.float32)
        rows, before, after, between = found
        return rows.joints[before] if not between else _turn_bones(rows.joints[before], rows.joints[after], between)


def _rows(values: Sequence, shape: tuple[int, ...]) -> np.ndarray:
    rows = np.full((len(values), *shape), np.nan, dtype=np.float32)
    held = [row for row, value in enumerate(values) if value is not None]
    if held:
        rows[held] = [values[row] for row in held]
    return rows


def unpack_hand_models(entries: Iterable[tuple[str, bytes]]) -> HandModels:
    """The hands of the ``(description, data)`` entries of one key, the result of `scene.custom_data(key)`."""
    parts = [json.loads(data) for _, data in entries]
    if not parts:
        raise ValueError("no entries of hand models")
    for part in parts:
        if part["format"] != _FORMAT or part["version"] != _VERSION or part["model"]["name"] != "soma":
            raise ValueError(f"expected {_FORMAT} version {_VERSION} of soma, got {part['format']} version {part['version']} of {part['model']['name']}")
    parts.sort(key=lambda part: part["begin"])
    chunks = tuple(HandChunk(part["begin"], part["end"], {name: HandRows(
        HandShape(hand["side"], np.array(hand["identity"], dtype=np.float32), float(hand["scale"]), np.array(hand["bones"], dtype=np.float32),
                  np.array(hand["bone_scales"], dtype=np.float32) if "bone_scales" in hand else None),
        _rows(hand["rotation"], (3,)), _rows(hand["translation"], (3,)), _rows(hand["articulation"], (_FINGER_JOINTS, 3)), _rows(hand["joints"], (_KEYPOINTS, 3)),
    ) for name, hand in part["hands"].items()}) for part in parts)
    return HandModels(parts[0]["model"], chunks, tuple(dict.fromkeys(name for chunk in chunks for name in chunk.hands)))


def hand_model_keys(scene: Scene) -> list[str]:
    """The keys of hand models that the video carries."""
    listed = {key for key, _ in scene.custom_data_keys()}
    return [key for key in HAND_MODEL_KEYS if key in listed]


def load_hand_models(scene: Scene, key: str) -> HandModels:
    """The hand models of a video under one key."""
    return unpack_hand_models(scene.custom_data(key))


def _turn_bones(first: np.ndarray, second: np.ndarray, between: float) -> np.ndarray:
    """The ``(21, 3)`` joints a fraction of the way between two rows: the wrist moves along a line, and each bone of `HAND_EDGES` turns along the shortest arc."""
    first, second = first.astype(np.float64), second.astype(np.float64)
    joints = first + between * (second - first)
    for parent, joint in HAND_EDGES:
        start, stop = first[joint] - first[parent], second[joint] - second[parent]
        start_length, stop_length = np.linalg.norm(start), np.linalg.norm(stop)
        start, stop = start / start_length, stop / stop_length
        theta = math.acos(min(max(float(start @ stop), -1.0), 1.0))
        direction = start + between * (stop - start) if math.sin(theta) < 1e-4 else (
            (math.sin((1.0 - between) * theta) * start + math.sin(between * theta) * stop) / math.sin(theta))
        joints[joint] = joints[parent] + (start_length + between * (stop_length - start_length)) * direction
    return joints.astype(np.float32)


def _quaternions(axis_angles: np.ndarray) -> np.ndarray:
    """The unit quaternions ``(..., 4)``, the real part first, of axis-angle vectors ``(..., 3)``."""
    theta = np.linalg.norm(axis_angles, axis=-1, keepdims=True)
    small = theta < 1e-4
    return np.concatenate((np.cos(0.5 * theta), np.where(small, 0.5, np.sin(0.5 * theta) / np.where(small, 1.0, theta)) * axis_angles), axis=-1)


def _slerp(first: np.ndarray, second: np.ndarray, between: float) -> np.ndarray:
    """The axis-angle vectors ``(..., 3)`` a fraction of the way from `first` to `second` along the shortest arc."""
    if not between:
        return first
    start, stop = _quaternions(first.astype(np.float64)), _quaternions(second.astype(np.float64))
    cosine = (start * stop).sum(axis=-1, keepdims=True)
    stop = np.where(cosine < 0.0, -stop, stop)
    theta = np.arccos(np.clip(np.abs(cosine), 0.0, 1.0))
    near = theta < 1e-4
    sine = np.where(near, 1.0, np.sin(theta))
    mixed = (np.where(near, 1.0 - between, np.sin((1.0 - between) * theta) / sine) * start
             + np.where(near, between, np.sin(between * theta) / sine) * stop)
    length = np.linalg.norm(mixed[..., 1:], axis=-1, keepdims=True)
    angle = 2.0 * np.arctan2(length, mixed[..., :1])
    return np.where(length < 1e-8, 2.0, angle / np.where(length < 1e-8, 1.0, length)) * mixed[..., 1:]


class SomaPoser:
    """SOMA-X: the `SOMAHandLayer` of https://github.com/NVlabs/SOMA-X, on the CPU. It reads the assets that the entries name, and downloads them the first time."""

    def __init__(self, model: dict):
        from soma.assets import get_assets_dir

        self._root = get_assets_dir(revision=model["assets"].rpartition("@")[2])
        self._lod = model["lod"]
        self._layers: dict = {}
        self._prepared: dict[str, tuple] = {}

    def _layer(self, side: str):
        if side not in self._layers:
            from soma import SOMAHandLayer

            self._layers[side] = SOMAHandLayer(data_root=self._root, hand_type=side, device="cpu", mode="torch", lod=self._lod, correctives_model_path=None)
        return self._layers[side]

    def faces(self, side: str) -> np.ndarray:
        return self._layer(side).faces.numpy()

    def _posed(self, shape: HandShape, articulation: np.ndarray, rotation: np.ndarray, translation: np.ndarray, fk_only: bool = False):
        """The output of the model for one pose, in scene units: `articulation` is relative to the bind pose, and joint 0 of the model takes `rotation`."""
        import torch

        layer = self._layer(shape.side)
        with torch.no_grad():
            prepared = (shape.identity.tobytes(), shape.scale, None if shape.bone_scales is None else shape.bone_scales.tobytes())
            if self._prepared.get(shape.side) != prepared:
                layer.prepare_identity(torch.from_numpy(shape.identity)[None], None if shape.bone_scales is None else torch.from_numpy(shape.bone_scales)[None], global_scale=shape.scale)
                self._prepared[shape.side] = prepared
            poses = torch.from_numpy(np.concatenate((rotation[None], articulation)).astype(np.float32))[None]
            return layer.pose(poses, global_translation=torch.from_numpy(np.asarray(translation, dtype=np.float32))[None], fk_only=fk_only,
                              reference_pose=layer.bind_pose_world[:, :3, :3])

    def pose(self, shape: HandShape, articulation: np.ndarray, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
        """The ``(V, 3)`` scene positions of the vertices."""
        return self._posed(shape, articulation, rotation, translation).vertices[0].numpy()

    def keypoints(self, shape: HandShape, articulation: np.ndarray, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
        """The ``(21, 3)`` scene positions of the joints of the model that match the hand keypoints, in the order of `HAND_EDGES`."""
        return self._posed(shape, articulation, rotation, translation, fk_only=True).joints[0].numpy()[_SOMA_KEYPOINTS]


def poser_for(models: HandModels) -> SomaPoser:
    """The poser of the hand model of `models`."""
    return SomaPoser(models.model)


def _pose_at(models: HandModels, hand: str, time: float) -> tuple[HandShape, np.ndarray, np.ndarray, np.ndarray] | None:
    """The shape, the articulation, the rotation and the translation of a hand at a time, ``None`` when the rows around the time have no data.

    Between two rows the rotations turn along the shortest arc and the translation moves along a line.
    """
    found = models.rows_at(hand, time)
    if found is None:
        return None
    rows, before, after, between = found
    if np.isnan(rows.rotation[[before, after]]).any():
        return None
    return (rows.shape, _slerp(rows.articulation[before], rows.articulation[after], between), _slerp(rows.rotation[before], rows.rotation[after], between),
            rows.translation[before] + between * (rows.translation[after] - rows.translation[before]))


def mesh_at(models: HandModels, poser: SomaPoser, hand: str, time: float) -> tuple[np.ndarray, np.ndarray] | None:
    """The ``(V, 3)`` vertices and the ``(T, 3)`` faces of a hand at a time, ``None`` when the rows around the time have no data. The bones keep their lengths between two rows."""
    pose = _pose_at(models, hand, time)
    return None if pose is None else (poser.pose(*pose), poser.faces(pose[0].side))


def keypoints_at(models: HandModels, poser: SomaPoser, hand: str, time: float) -> np.ndarray:
    """The ``(21, 3)`` keypoints of the hand model at a time, in the order of `HAND_EDGES`, NaN with no data. The bones keep their lengths between two rows."""
    pose = _pose_at(models, hand, time)
    return np.full((_KEYPOINTS, 3), np.nan) if pose is None else poser.keypoints(*pose)


def keypoint_track(models: HandModels, poser: SomaPoser, hand: str) -> tuple[np.ndarray, np.ndarray]:
    """The ``(N,)`` times in seconds of all the rows of a hand, and the ``(N, 21, 3)`` keypoints of the hand model at those times, NaN where a row has no data."""
    times = sorted({(chunk.begin + row * (chunk.end - chunk.begin) / (len(chunk.hands[hand].rotation) - 1)) / 1e6
                    for chunk in models.chunks if hand in chunk.hands for row in range(len(chunk.hands[hand].rotation))})
    return np.array(times), np.stack([keypoints_at(models, poser, hand, time) for time in times])


def draw_mesh(image: np.ndarray, camera: CameraSetup, vertices: np.ndarray, faces: np.ndarray,
              color: Sequence[float] = MESH_COLOR, opacity: float = 0.6) -> np.ndarray:
    """Draw a shaded mesh seen from `camera` into a ``(H, W, C)`` image in place, like `draw_points`: over the splats, with no depth test."""
    height, width = image.shape[:2]
    full = 255.0 if np.issubdtype(image.dtype, np.integer) else 1.0
    view = np.linalg.inv(camera.camera_transform.astype(np.float64))
    seen = np.c_[vertices, np.ones(len(vertices))] @ view
    clip = seen @ camera.projection.astype(np.float64)
    faces = faces[(clip[:, 3] > 0.0)[faces].all(axis=1)]
    if not len(faces):
        return image
    pixels = (clip[:, :2] / clip[:, 3:] + 1.0) * 0.5 * (width, height)
    corners = seen[faces, :3]
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    centers = corners.mean(axis=1)
    facing = np.abs((normals * centers).sum(axis=1)) / (np.linalg.norm(normals, axis=1) * np.linalg.norm(centers, axis=1) + 1e-12)
    ink = np.outer(0.35 + 0.65 * facing, color) * full
    buffer = Image.new("I", (width, height))
    painter = ImageDraw.Draw(buffer)
    polygons = pixels[faces].reshape(len(faces), -1).tolist()
    for face in np.argsort(-clip[faces, 3].mean(axis=1)).tolist():
        painter.polygon(polygons[face], fill=face + 1)
    drawn = np.asarray(buffer)
    covered = drawn > 0
    image[covered, :3] = (1.0 - opacity) * image[covered, :3] + opacity * ink[drawn[covered] - 1]
    return image


def draw_hand_models(image: np.ndarray, camera: CameraSetup, models: HandModels, time: float, poser: SomaPoser | None = None,
                   hands: Sequence[str] | None = None, square: int = 6, line: int = 2) -> np.ndarray:
    """Draw each hand at a time into an image in place: with a poser, the mesh and the keypoints of the hand model; with no poser, the stored joints."""
    for name in models.hands if hands is None else hands:
        mesh = mesh_at(models, poser, name, time) if poser is not None else None
        if mesh is not None:
            draw_mesh(image, camera, *mesh)
        points = models.joints_at(name, time) if poser is None else keypoints_at(models, poser, name, time)
        draw_points(image, camera, points, HAND_EDGES, JOINT_COLOR, square, line)
    return image


def close_up(camera: CameraSetup, points: np.ndarray, aspect: float = 1.0) -> CameraSetup:
    """A camera at the place of `camera` that turns to frame ``(N, 3)`` points; NaN points do not count."""
    points = points[~np.isnan(points).any(axis=1)].astype(np.float64)
    center = points.mean(axis=0)
    eye = camera.camera_transform[3, :3].astype(np.float64)
    radius = 1.3 * float(np.linalg.norm(points - center, axis=1).max())
    fov = 2.0 * math.asin(min(radius / float(np.linalg.norm(center - eye)), 0.99))
    view = look_at(eye, center, camera.camera_transform[1, :3])
    return make_camera(perspective(fov, aspect, 0.01, 100.0), np.linalg.inv(view.T).T)
