"""First-party, optional person detector runtime.

The worker is deliberately a small, fail-closed library.  It accepts only a
bounded RGBA frame supplied by an already-authorized job; it never resolves a
camera URL, reads a Secret, or writes frames to disk.  ``onnxruntime`` is an
optional runtime dependency: when it is unavailable the caller receives the
stable ``runtime_unavailable`` result instead of a silent CPU fallback.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import pathlib
import re
import time
from typing import Any

MODEL_ID = "ssd-mobilenet-v1-12-person"
MODEL_VERSION = "onnx-model-zoo-4c46cd00"
MODEL_SHA256 = "b8fba5e404077d4048d27fcd1667e85e27e192eb9bf51e696c46a3acd7d21058"
MAX_FRAME_BYTES = 160 * 90 * 4
MAX_BOXES = 16
MODEL_SIZE = 300


class DetectorError(RuntimeError):
    """A non-sensitive detector failure suitable for an OperationalIssue."""


def verify_model(model_path: pathlib.Path, expected_sha256: str = MODEL_SHA256) -> bytes:
    if not model_path.is_absolute() or model_path.is_symlink() or not model_path.is_file():
        raise DetectorError("model_unavailable")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise DetectorError("model_manifest_invalid")
    try:
        data = model_path.read_bytes()
    except OSError as error:
        raise DetectorError("model_unavailable") from error
    if len(data) > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise DetectorError("model_integrity_failed")
    return data


def _boxes(outputs: dict[str, Any], names: list[str], threshold: float,
           transform: tuple[float, float, float, float]) -> list[dict[str, float]]:
    if len(names) < 4:
        raise DetectorError("model_output_invalid")
    arrays = [getattr(outputs.get(name), "reshape", lambda *_: [])(-1) for name in names[:4]]
    count = min(int(float(arrays[0][0])) if len(arrays[0]) else 0, 100)
    offset_x, offset_y, scaled_width, scaled_height = transform
    result: list[dict[str, float]] = []
    for index in range(count):
        score = float(arrays[2][index]) if index < len(arrays[2]) else 0
        label = int(float(arrays[3][index])) if index < len(arrays[3]) else -1
        if label != 1 or score < threshold or index * 4 + 3 >= len(arrays[1]):
            continue
        top, left, bottom, right = (max(0.0, min(1.0, float(arrays[1][index * 4 + offset]))) * MODEL_SIZE for offset in range(4))
        top = max(0.0, min(1.0, (top - offset_y) / scaled_height))
        left = max(0.0, min(1.0, (left - offset_x) / scaled_width))
        bottom = max(top, min(1.0, (bottom - offset_y) / scaled_height))
        right = max(left, min(1.0, (right - offset_x) / scaled_width))
        if bottom < top or right < left:
            continue
        result.append({"x": left, "y": top, "width": right - left, "height": bottom - top,
                       "confidence": max(0.0, min(1.0, score))})
        if len(result) >= MAX_BOXES:
            break
    return result


class PersonDetector:
    def __init__(self, model_path: pathlib.Path):
        self.model_path = model_path
        self._model = verify_model(model_path)
        try:
            self.ort = importlib.import_module("onnxruntime")
        except ImportError as error:
            raise DetectorError("runtime_unavailable") from error
        try:
            self.session = self.ort.InferenceSession(self._model, providers=["CPUExecutionProvider"])
        except Exception as error:  # provider errors are intentionally generic
            raise DetectorError("runtime_unavailable") from error

    def infer(self, rgba: bytes, width: int, height: int, threshold: float = .6) -> list[dict[str, float]]:
        if not isinstance(width, int) or not isinstance(height, int) or width < 2 or height < 2 or \
                width * height * 4 != len(rgba) or len(rgba) > MAX_FRAME_BYTES:
            raise DetectorError("frame_invalid")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not .05 <= threshold <= 1:
            raise DetectorError("threshold_invalid")
        try:
            import numpy as np
            image = np.frombuffer(rgba, dtype=np.uint8).reshape((height, width, 4))[:, :, :3]
            scale = min(MODEL_SIZE / width, MODEL_SIZE / height)
            scaled_width = max(1, round(width * scale))
            scaled_height = max(1, round(height * scale))
            offset_x = (MODEL_SIZE - scaled_width) / 2
            offset_y = (MODEL_SIZE - scaled_height) / 2
            ys = (np.arange(scaled_height) * height // scaled_height).astype(int)
            xs = (np.arange(scaled_width) * width // scaled_width).astype(int)
            tensor = np.full((MODEL_SIZE, MODEL_SIZE, 3), 114, dtype=np.uint8)
            tensor[int(round(offset_y)):int(round(offset_y)) + scaled_height,
                   int(round(offset_x)):int(round(offset_x)) + scaled_width, :] = image[ys[:, None], xs[None, :], :]
            tensor = tensor[None, :, :, :]
            input_name = self.session.get_inputs()[0].name
            output_values = self.session.run(None, {input_name: tensor})
            outputs = {item.name: value for item, value in zip(self.session.get_outputs(), output_values)}
            return _boxes(outputs, [item.name for item in self.session.get_outputs()], float(threshold),
                          (offset_x, offset_y, scaled_width, scaled_height))
        except DetectorError:
            raise
        except Exception as error:
            raise DetectorError("inference_failed") from error


class DetectorJobRunner:
    """Execute one controller-authorized frame without resolving media itself.

    The caller must obtain the frame from the controller's short-lived,
    Camera/Profile-bound media grant.  This class intentionally accepts bytes
    only; it has no URL, Secret, socket, or arbitrary filesystem input.
    """

    def __init__(self, model_path: pathlib.Path):
        self.detector = PersonDetector(model_path)

    def process(self, job: dict[str, Any], rgba: bytes, width: int, height: int,
                *, threshold: float = .6, occurred_at: int | None = None) -> dict[str, Any]:
        if not isinstance(job, dict) or job.get("kind") != "person" or \
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", str(job.get("jobId", ""))) or \
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", str(job.get("cameraId", ""))) or \
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", str(job.get("profileId", ""))) or \
                job.get("modelId") != MODEL_ID or job.get("modelSha256") != MODEL_SHA256:
            raise DetectorError("job_invalid")
        boxes = self.detector.infer(rgba, width, height, threshold)
        timestamp = int(time.time() * 1000) if occurred_at is None else occurred_at
        return result_metadata(boxes, job_id=job["jobId"], camera_id=job["cameraId"],
                               profile_id=job["profileId"], occurred_at=timestamp,
                               model_sha256=MODEL_SHA256)


def result_metadata(boxes: list[dict[str, float]], *, job_id: str, camera_id: str, profile_id: str,
                    occurred_at: int, model_sha256: str = MODEL_SHA256) -> dict[str, Any]:
    """Return bounded metadata only; frame bytes and paths are never serialized."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", job_id) or \
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", camera_id) or \
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", profile_id):
        raise DetectorError("identity_invalid")
    if not isinstance(boxes, list) or not isinstance(occurred_at, int) or isinstance(occurred_at, bool) or \
            not re.fullmatch(r"[0-9a-f]{64}", model_sha256):
        raise DetectorError("result_invalid")
    safe = []
    for box in boxes[:MAX_BOXES]:
        if not isinstance(box, dict):
            raise DetectorError("result_invalid")
        try:
            values = {key: float(box[key]) for key in ("x", "y", "width", "height", "confidence")}
        except (KeyError, TypeError, ValueError) as error:
            raise DetectorError("result_invalid") from error
        if any(value < 0 or value > 1 for value in values.values()) or \
                values["x"] + values["width"] > 1 or values["y"] + values["height"] > 1:
            raise DetectorError("result_invalid")
        safe.append(values)
    return {"jobId": job_id, "cameraId": camera_id, "profileId": profile_id, "kind": "person",
            "occurredAt": int(occurred_at), "boxes": safe, "modelId": MODEL_ID,
            "modelVersion": MODEL_VERSION, "modelSha256": model_sha256}


if __name__ == "__main__":
    # This command is a supply-chain/runtime probe, not a network service.
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/opt/webobs/ui/models/ssd_mobilenet_v1_12.onnx")
    parser.add_argument("--serve", action="store_true", help="keep a local worker runtime alive for controller job integration")
    args = parser.parse_args()
    verify_model(pathlib.Path(args.model))
    print(json.dumps({"status": "model-verified", "modelId": MODEL_ID, "serve": args.serve}, separators=(",", ":")), flush=True)
    if args.serve:
        import signal
        nonlocal_stop = [False]
        def request_stop(*_args: object) -> None:
            nonlocal_stop[0] = True
        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        while not nonlocal_stop[0]:
            import time
            time.sleep(1)
