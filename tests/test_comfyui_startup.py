from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from tests._helpers import PROJECT_ROOT  # noqa: F401

import comfyui_utils


GPU_1 = "http://127.0.0.1:8188"
GPU_2 = "http://127.0.0.1:8189"


class TestComfyUIStartupReadiness(unittest.TestCase):
    def setUp(self):
        self._old_env = {
            "COMFYUI_URLS": os.environ.get("COMFYUI_URLS"),
            "FANTASEE_AUTO_SPAWN_CPU": os.environ.get("FANTASEE_AUTO_SPAWN_CPU"),
        }
        comfyui_utils._cpu_spawn_attempted = False
        comfyui_utils._worker_kinds.clear()

    def tearDown(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        comfyui_utils._cpu_spawn_attempted = False
        comfyui_utils._worker_kinds.clear()

    def _status_for(self, healthy_urls):
        healthy = set(healthy_urls)

        def status(url, timeout=1.5):
            return {"running": url in healthy, "url": url}

        return status

    def test_one_configured_healthy_worker_satisfies_startup_wait(self):
        os.environ["COMFYUI_URLS"] = f"{GPU_1},{GPU_2}"

        with patch.object(comfyui_utils, "is_running_at", side_effect=self._status_for([GPU_1])), \
                patch.object(comfyui_utils.time, "sleep") as sleep:
            workers = comfyui_utils.ensure_workers(
                min_workers=1,
                wait_for_spawn=True,
                wait_timeout=120,
            )

        self.assertEqual(workers, [GPU_1, GPU_2])
        sleep.assert_not_called()

    def test_default_gpu_does_not_spawn_unneeded_second_worker(self):
        os.environ.pop("COMFYUI_URLS", None)
        os.environ["FANTASEE_AUTO_SPAWN_CPU"] = "1"

        with patch.object(comfyui_utils, "is_running_at", side_effect=self._status_for([GPU_1])), \
                patch.object(comfyui_utils, "_spawn_cpu_comfyui") as spawn:
            workers = comfyui_utils.ensure_workers(min_workers=1, wait_for_spawn=False)

        self.assertEqual(workers, [GPU_1])
        spawn.assert_not_called()

    def test_missing_default_worker_spawns_one_required_worker(self):
        os.environ.pop("COMFYUI_URLS", None)
        os.environ["FANTASEE_AUTO_SPAWN_CPU"] = "1"
        calls = {"spawned": False}

        def status(url, timeout=1.5):
            return {"running": calls["spawned"] and url == GPU_2, "url": url}

        def spawn(port):
            calls["spawned"] = True

        with patch.object(comfyui_utils, "is_running_at", side_effect=status), \
                patch.object(comfyui_utils, "_spawn_cpu_comfyui", side_effect=spawn) as spawn_mock, \
                patch.object(comfyui_utils.time, "sleep"):
            workers = comfyui_utils.ensure_workers(
                min_workers=1,
                wait_for_spawn=True,
                wait_timeout=5,
            )

        spawn_mock.assert_called_once_with(8189)
        self.assertEqual(workers, [GPU_2])
        self.assertEqual(os.environ.get("COMFYUI_URLS"), GPU_2)

    def test_optional_local_worker_is_discovered_without_being_required(self):
        os.environ.pop("COMFYUI_URLS", None)
        os.environ["FANTASEE_AUTO_SPAWN_CPU"] = "1"

        with patch.object(comfyui_utils, "is_running_at", side_effect=self._status_for([GPU_1, GPU_2])), \
                patch.object(comfyui_utils, "_spawn_cpu_comfyui") as spawn:
            workers = comfyui_utils.ensure_workers(min_workers=1, wait_for_spawn=False)

        self.assertEqual(workers, [GPU_1, GPU_2])
        spawn.assert_not_called()

    def test_parallel_generation_dispatches_only_to_healthy_workers(self):
        jobs = [
            {"prompt": "scene one", "output_prefix": "one"},
            {"prompt": "scene two", "output_prefix": "two"},
            {"prompt": "scene three", "output_prefix": "three"},
        ]
        used_bases = []

        def generate_to_base(base, prompt, output_prefix, output_dir, **kwargs):
            used_bases.append(base)
            return f"{output_prefix}.png"

        with patch.object(comfyui_utils, "ensure_workers", return_value=[GPU_1, GPU_2]) as ensure, \
                patch.object(comfyui_utils, "_healthy_bases", return_value=[GPU_1]), \
                patch.object(comfyui_utils, "_generate_image_to_base", side_effect=generate_to_base):
            results = comfyui_utils.generate_images_parallel(jobs, output_dir="unused")

        ensure.assert_called_once_with(min_workers=1, wait_for_spawn=True, wait_timeout=90)
        self.assertEqual(results, ["one.png", "two.png", "three.png"])
        self.assertEqual(used_bases, [GPU_1, GPU_1, GPU_1])

    def test_gpu_parallel_jobs_never_dispatch_to_cpu_worker(self):
        cpu = "http://127.0.0.1:8190"
        os.environ["COMFYUI_URLS"] = f"{GPU_1},{cpu}"
        comfyui_utils._worker_kinds.update({GPU_1: "gpu", cpu: "cpu"})
        used_bases = []

        def generate_to_base(base, prompt, output_prefix, output_dir, **kwargs):
            used_bases.append(base)
            return f"{output_prefix}.png"

        jobs = [
            {"prompt": "gpu one", "output_prefix": "one", "worker_kind": "gpu"},
            {"prompt": "gpu two", "output_prefix": "two", "worker_kind": "gpu"},
        ]
        with patch.object(comfyui_utils, "ensure_workers", return_value=[GPU_1, cpu]), \
                patch.object(comfyui_utils, "_healthy_bases", return_value=[GPU_1, cpu]), \
                patch.object(comfyui_utils, "_generate_image_to_base", side_effect=generate_to_base):
            results = comfyui_utils.generate_images_parallel(jobs, output_dir="unused")

        self.assertEqual(results, ["one.png", "two.png"])
        self.assertEqual(used_bases, [GPU_1, GPU_1])

    def test_constrained_picker_returns_none_without_matching_worker(self):
        with patch.object(comfyui_utils, "_healthy_bases", return_value=[GPU_1]):
            comfyui_utils._worker_kinds[GPU_1] = "gpu"
            self.assertIsNone(comfyui_utils._pick_healthy_base("cpu"))


if __name__ == "__main__":
    unittest.main()
