from __future__ import annotations

import hashlib
import importlib.util
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = Path(os.environ.get("WEBOBS_TEST_DETECTOR_WORKER", str(ROOT / "analytics" / "detector_worker.py")))
_LOADER = SourceFileLoader("webobs_detector_worker_test", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(_LOADER.name, _LOADER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DetectorWorkerTests(unittest.TestCase):
    def test_model_hash_and_metadata_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.onnx"
            path.write_bytes(b"fixture-model")
            digest = hashlib.sha256(b"fixture-model").hexdigest()
            self.assertEqual(MODULE.verify_model(path, digest), b"fixture-model")
            metadata = MODULE.result_metadata([{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4, "confidence": 0.9}],
                                              job_id="job-1", camera_id="cam-1", profile_id="sub", occurred_at=1,
                                              model_sha256=digest)
            self.assertEqual(metadata["kind"], "person")
            self.assertEqual(len(metadata["boxes"]), 1)
            self.assertNotIn("frame", metadata)
            with self.assertRaises(MODULE.DetectorError): MODULE.verify_model(path, "0" * 64)

    def test_person_postprocess_is_person_only_and_maps_letterbox(self) -> None:
        class Values:
            def __init__(self, values): self.values = values
            def reshape(self, _shape): return self.values

        outputs = {
            "count": Values([2]),
            "boxes": Values([0.0, 0.0, 1.0, 0.5, 0.0, 0.0, 1.0, 1.0]),
            "scores": Values([0.95, 0.99]),
            "classes": Values([1, 3]),
        }
        # A 160x90 frame is letterboxed vertically into 300x300. The first
        # model box maps back to the source frame, while the second class is
        # rejected even though its confidence is higher.
        boxes = MODULE._boxes(outputs, ["count", "boxes", "scores", "classes"], .6,
                              (0.0, 65.5, 300.0, 169.0))
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["x"], 0.0)
        self.assertEqual(boxes[0]["width"], 0.5)
        self.assertEqual(boxes[0]["height"], 1.0)

    def test_job_runner_requires_controller_model_contract_and_never_reads_media(self) -> None:
        runner = MODULE.DetectorJobRunner.__new__(MODULE.DetectorJobRunner)
        class FakeDetector:
            def infer(self, rgba, width, height, threshold):
                self.last = (rgba, width, height, threshold)
                return []
        runner.detector = FakeDetector()
        job = {"jobId": "job-1", "cameraId": "cam-1", "profileId": "sub", "kind": "person",
               "modelId": MODULE.MODEL_ID, "modelSha256": MODULE.MODEL_SHA256}
        result = runner.process(job, b"", 2, 2, occurred_at=1000)
        self.assertEqual(result["boxes"], [])
        self.assertEqual(runner.detector.last[:3], (b"", 2, 2))
        with self.assertRaises(MODULE.DetectorError):
            runner.process({**job, "modelSha256": "0" * 64}, b"", 2, 2)


if __name__ == "__main__":
    unittest.main()
