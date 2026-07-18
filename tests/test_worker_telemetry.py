from __future__ import annotations

from unittest.mock import patch
import os

import comfyui_utils


def test_process_cpu_percent_is_normalized_to_machine_capacity():
    assert comfyui_utils._normalize_process_cpu_percent(320, logical_cpus=8) == 40.0
    assert comfyui_utils._normalize_process_cpu_percent(1200, logical_cpus=8) == 100.0


def test_worker_telemetry_uses_gpu_engine_sample_for_gpu_workers():
    with patch.object(comfyui_utils, "_process_cpu_usage", return_value=(31.2, "windows-process")), \
            patch.object(comfyui_utils, "_windows_gpu_usage", return_value=72.4):
        telemetry = comfyui_utils._worker_telemetry(9624, "gpu")

    assert telemetry["gpu_percent"] == 72.4
    assert telemetry["cpu_percent"] == 31.2
    assert telemetry["cpu_source"] == "windows-process"
    assert telemetry["gpu_source"] == "windows-gpu-engine"
    assert telemetry["source"] == "windows-gpu-engine"


def test_worker_telemetry_uses_process_sample_for_cpu_workers():
    with patch.object(comfyui_utils, "_process_cpu_usage", return_value=(18.5, "windows-process")):
        telemetry = comfyui_utils._worker_telemetry(9624, "cpu")

    assert telemetry["cpu_percent"] == 18.5
    assert telemetry["gpu_percent"] is None
    assert telemetry["source"] == "windows-process"


def test_worker_telemetry_is_explicitly_unavailable_without_a_pid():
    telemetry = comfyui_utils._worker_telemetry(None, "gpu")

    assert telemetry["gpu_percent"] is None
    assert telemetry["cpu_percent"] is None
    assert telemetry["source"] == "unavailable"


def test_rendering_mode_limits_default_dispatch_to_the_selected_worker_kind():
    with patch.dict(os.environ, {"FANTASEE_RENDERING_MODE": "basic"}, clear=False), \
            patch.object(comfyui_utils, "_healthy_bases", return_value=["cpu", "gpu"]), \
            patch.object(comfyui_utils, "_worker_kind", side_effect=lambda url: url):
        assert comfyui_utils._pick_healthy_base() == "cpu"

    with patch.dict(os.environ, {"FANTASEE_RENDERING_MODE": "gpu"}, clear=False), \
            patch.object(comfyui_utils, "_healthy_bases", return_value=["cpu", "gpu"]), \
            patch.object(comfyui_utils, "_worker_kind", side_effect=lambda url: url):
        assert comfyui_utils._pick_healthy_base() == "gpu"
