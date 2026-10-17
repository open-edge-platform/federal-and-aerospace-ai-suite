# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/camera_config.py (run with tests/camera_config/run_tests.sh)."""
import copy
import json
import os
import sys
import tempfile
import unittest

import jsonschema
import yaml

REPO = os.environ.get("REPO_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import camera_config as cc  # noqa: E402

CAMERA = {"id": "front_camera"}


def config(*cameras):
    return cc.parse_config({"version": 1, "cameras": [dict(c) for c in cameras]})


def plan_of(camera: dict) -> cc.CameraPlan:
    return cc.build_plan(config(camera), check_files=False)[0]


class DefaultsAndNames(unittest.TestCase):
    def test_shipped_file_is_valid(self):
        cfg = cc.load_config(os.path.join(REPO, "configs", "cameras.yaml"))
        self.assertEqual([c.id for c in cfg.cameras], ["front_camera", "bottom_camera", "back_camera"])
        for plan in cc.build_plan(cfg, check_files=False):
            self.assertEqual(plan.pipeline, "uav_object_detection_npu_gpu")

    def test_pipeline_name_for_every_combination(self):
        for det in ("cpu", "gpu", "npu"):
            self.assertEqual(plan_of({**CAMERA, "detection": {"device": det}}).pipeline, f"uav_object_detection_{det}")
            for vlm in ("cpu", "gpu"):
                camera = {**CAMERA, "detection": {"device": det}, "captioning": {"enabled": True, "device": vlm}}
                self.assertEqual(plan_of(camera).pipeline, f"uav_object_detection_{det}_{vlm}")

    def test_captioning_off_ignores_vlm_settings(self):
        plan = plan_of({**CAMERA, "captioning": {"enabled": False, "device": "cpu"}})
        self.assertEqual(plan.pipeline, "uav_object_detection_npu")
        self.assertNotIn("captioner_prompt", plan.request["parameters"])
        self.assertIsNone(plan.mqtt_topic)


class PlanContent(unittest.TestCase):
    def test_request_shape(self):
        plan = plan_of({**CAMERA, "video": "uav_sample_front.avi", "captioning": {"enabled": True, "prompt": "Count the cars."}})
        frame = plan.request["destination"]["frame"]
        self.assertEqual((frame["type"], frame["path"], frame["encoding"]), ("rtsp", "uav-front-camera", "h264"))
        self.assertNotIn("overlay", frame)                                  # on by default
        params = plan.request["parameters"]
        self.assertEqual(params["video"], "uav_sample_front.avi")
        self.assertEqual(params["captioner_prompt"], "Count the cars.")
        self.assertEqual(params["captioner_model_path"], f"{cc.RESOURCES_DIR}/ov_models/gpu/InternVL2-1B")
        self.assertEqual(params["mqtt_topic"], "uav/caption/front_camera")
        self.assertEqual(params["detection_model"], f"{cc.RESOURCES_DIR}/models/yolo11s/yolo11s_openvino_model/yolo11s.xml")

    def test_overlay_off_is_sent_to_the_destination(self):
        self.assertIs(plan_of({**CAMERA, "overlay": False}).request["destination"]["frame"]["overlay"], False)

    def test_overrides_for_stream_path_and_topic(self):
        plan = plan_of({**CAMERA, "rtsp_path": "my-stream", "mqtt_topic": "uav/caption/mine", "captioning": {"enabled": True}})
        self.assertEqual((plan.rtsp_path, plan.mqtt_topic), ("my-stream", "uav/caption/mine"))

    def test_disabled_cameras_are_not_planned(self):
        plans = cc.build_plan(config(CAMERA, {"id": "b_camera", "enabled": False}), check_files=False)
        self.assertEqual([p.camera_id for p in plans], ["front_camera"])

    def test_model_instances_are_shared_only_for_the_same_device_and_model(self):
        plans = cc.build_plan(config(
            {"id": "a"}, {"id": "b"}, {"id": "c", "detection": {"model": "other/model/other.xml"}}, {"id": "d", "detection": {"device": "gpu"}}),
            check_files=False)
        ids = {p.camera_id: p.request["parameters"]["detection_instance_id"] for p in plans}
        self.assertEqual(ids["a"], ids["b"])
        self.assertEqual(len({ids["a"], ids["c"], ids["d"]}), 3)
        self.assertEqual(ids["a"], "instnpu_yolo11s")

    def test_missing_files_are_reported(self):
        with tempfile.TemporaryDirectory() as resources:
            os.makedirs(f"{resources}/videos")
            with self.assertRaises(cc.ConfigError) as ctx:
                cc.build_plan(config({**CAMERA, "captioning": {"enabled": True}}), resources_dir=resources)
            message = str(ctx.exception)
            self.assertIn("video not found", message)
            self.assertIn("detection model not found", message)
            self.assertIn("captioning model not found", message)


class Validation(unittest.TestCase):
    def assertRejected(self, data, fragment):
        with self.assertRaises(cc.ConfigError) as ctx:
            cc.parse_config(data)
        self.assertIn(fragment, str(ctx.exception))

    def cam(self, **fields):
        return {"version": 1, "cameras": [{**CAMERA, **fields}]}

    def test_vlm_cannot_run_on_npu(self):
        self.assertRejected(self.cam(captioning={"enabled": True, "device": "npu"}), "cameras.0.captioning.device")

    def test_unknown_detection_device(self):
        self.assertRejected(self.cam(detection={"device": "tpu"}), "cameras.0.detection.device")

    def test_misspelled_keys_are_errors(self):
        self.assertRejected(self.cam(overlays=False), "Extra inputs are not permitted")
        self.assertRejected(self.cam(captioning={"enable": True}), "captioning.enable")

    def test_ids(self):
        for bad in ("Front", "1cam", "a b", "a/b", "", "x" * 33):
            self.assertRejected({"version": 1, "cameras": [{"id": bad}]}, "cameras.0.id")

    def test_videos_cannot_escape_the_folder(self):
        for bad in ("../x.avi", "/etc/passwd.avi", "a/b.avi", "clip.exe", "clip"):
            self.assertRejected(self.cam(video=bad), "cameras.0.video")

    def test_models_cannot_escape_the_models_folder(self):
        for bad in ("../x.xml", "/abs/m.xml", "a/../b.xml", "m.bin", "a b.xml"):
            self.assertRejected(self.cam(detection={"model": bad}), "cameras.0.detection.model")
        self.assertRejected(self.cam(captioning={"enabled": True, "model": "../x"}), "cameras.0.captioning.model")

    def test_prompt_cannot_break_the_pipeline_string(self):
        for bad in ('say "hi"', "a{b}", "a\nb", "a;b", "a\\b", ""):
            self.assertRejected(self.cam(captioning={"enabled": True, "prompt": bad}), "captioning.prompt")

    def test_token_limits(self):
        for bad in (0, 4097):
            self.assertRejected(self.cam(captioning={"enabled": True, "max_new_tokens": bad}), "max_new_tokens")

    def test_duplicates(self):
        self.assertRejected({"version": 1, "cameras": [{"id": "a"}, {"id": "a"}]}, "duplicate camera id 'a'")
        self.assertRejected({"version": 1, "cameras": [{"id": "a", "rtsp_path": "s"}, {"id": "b", "rtsp_path": "s"}]}, "duplicate RTSP path 's'")

    def test_topic_and_path_patterns(self):
        self.assertRejected(self.cam(mqtt_topic="other/topic"), "mqtt_topic")
        self.assertRejected(self.cam(rtsp_path="a/b"), "rtsp_path")

    def test_version_and_shape(self):
        self.assertRejected({"version": 2, "cameras": [{"id": "a"}]}, "unsupported version 2")
        self.assertRejected({"version": 1, "cameras": []}, "cameras")
        self.assertRejected(["not", "a", "mapping"], "must be a mapping")

    def test_every_problem_is_listed(self):
        with self.assertRaises(cc.ConfigError) as ctx:
            cc.parse_config(self.cam(video="../x.avi", detection={"device": "tpu"}, overlays=1))
        self.assertGreaterEqual(len(str(ctx.exception).splitlines()), 3)


class Loading(unittest.TestCase):
    def write(self, text, suffix=".yaml"):
        handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_yaml_and_json_files(self):
        self.assertEqual(cc.load_config(self.write("version: 1\ncameras:\n  - id: a\n")).cameras[0].id, "a")
        self.assertEqual(cc.load_config(self.write('{"version": 1, "cameras": [{"id": "b"}]}', ".json")).cameras[0].id, "b")

    def test_yaml_booleans_do_not_turn_devices_into_booleans(self):
        # YAML 1.1 reads no/off/on as booleans; the schema must reject them instead of accepting a wrong type
        with self.assertRaises(cc.ConfigError):
            cc.load_config(self.write("version: 1\ncameras:\n  - id: a\n    detection: {device: on}\n"))

    def test_unreadable_and_broken_files(self):
        with self.assertRaises(cc.ConfigError) as ctx:
            cc.load_config("/nonexistent/cameras.yaml")
        self.assertIn("cannot read", str(ctx.exception))
        with self.assertRaises(cc.ConfigError) as ctx:
            cc.load_config(self.write("cameras: [ {"))
        self.assertIn("not valid YAML", str(ctx.exception))

    def test_unsafe_yaml_tags_are_not_executed(self):
        with self.assertRaises(cc.ConfigError):
            cc.load_config(self.write("version: 1\ncameras: !!python/object/apply:os.system ['true']\n"))

    def test_json_schema_for_forms(self):
        schema = cc.json_schema()
        self.assertIn("cameras", schema["properties"])
        self.assertEqual(sorted(schema["$defs"]["Detection"]["properties"]["device"]["enum"]), ["cpu", "gpu", "npu"])
        self.assertEqual(sorted(schema["$defs"]["Captioning"]["properties"]["device"]["enum"]), ["cpu", "gpu"])


class MatchesThePipelineDefinitions(unittest.TestCase):
    """Every request this module builds must satisfy the parameter schema of the pipeline it targets."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(REPO, "configs", "config-pymavlink-pipelines.json")
        with open(path, encoding="utf-8") as handle:
            cls.pipelines = {p["name"]: p for p in json.load(handle)["config"]["pipelines"]}

    def test_all_nine_pipelines_exist(self):
        expected = {f"uav_object_detection_{d}" for d in ("cpu", "gpu", "npu")} | {
            f"uav_object_detection_{d}_{v}" for d in ("cpu", "gpu", "npu") for v in ("cpu", "gpu")}
        self.assertEqual(expected, set(self.pipelines) & expected)

    def test_requests_satisfy_the_pipeline_schemas(self):
        for det in ("cpu", "gpu", "npu"):
            for vlm in (None, "cpu", "gpu"):
                camera = {**CAMERA, "detection": {"device": det}, "captioning": {"enabled": vlm is not None, "device": vlm or "gpu"}}
                plan = plan_of(camera)
                schema = self.pipelines[plan.pipeline]["parameters"]
                try:
                    jsonschema.validate(plan.request["parameters"], schema)
                except jsonschema.ValidationError as exc:
                    self.fail(f"{plan.pipeline}: {exc.message}")

    def test_every_parameter_sent_is_known_to_the_pipeline(self):
        for plan in cc.build_plan(config(CAMERA, {"id": "b", "captioning": {"enabled": True}}), check_files=False):
            unknown = set(plan.request["parameters"]) - set(self.pipelines[plan.pipeline]["parameters"]["properties"])
            self.assertFalse(unknown, f"{plan.pipeline}: {unknown}")

    def test_shared_pipelines_schemas_reject_bad_values(self):
        schema = self.pipelines["uav_object_detection_npu_gpu"]["parameters"]
        for key, bad in (("video", "../x.avi"), ("captioner_prompt", 'a"b'), ("mqtt_topic", "x/y"), ("detection_instance_id", "A b")):
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate({key: bad}, copy.deepcopy(schema))


if __name__ == "__main__":
    unittest.main(verbosity=2)
