"""Focused regression tests for the public-repository security boundaries."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from fantasee_server.api.settings import _mask_settings
from fantasee_server.paths import generated_story_dir
from fantasee_server.security import (
    authorize_client,
    validate_provider_url,
    validate_provider_urls,
)
from story_storage import validate_story_id


class SecurityBoundaryTests(unittest.TestCase):
    def test_loopback_remains_usable_without_operator_token(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FANTASEE_API_TOKEN", None)
            os.environ.pop("FANTASEE_REQUIRE_AUTH", None)
            authorize_client("127.0.0.1", None)

    def test_non_loopback_requires_operator_token(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FANTASEE_API_TOKEN", None)
            os.environ.pop("FANTASEE_REQUIRE_AUTH", None)
            with self.assertRaisesRegex(HTTPException, "Operator authentication"):
                authorize_client("192.168.1.10", None)

    def test_operator_token_is_constant_time_checked(self):
        with patch.dict(os.environ, {"FANTASEE_API_TOKEN": "test-token"}, clear=False):
            with self.assertRaisesRegex(HTTPException, "Operator authentication"):
                authorize_client("192.168.1.10", "Bearer wrong-token")
            authorize_client("192.168.1.10", "Bearer test-token")

    def test_provider_policy_allows_local_comfy_and_default_host(self):
        self.assertEqual(
            validate_provider_url("http://127.0.0.1:8188/", kind="comfyui"),
            "http://127.0.0.1:8188",
        )
        with patch(
            "fantasee_server.security._resolved_addresses",
            return_value=["8.8.8.8"],
        ):
            self.assertEqual(
                validate_provider_url(
                    "https://token-plan-sgp.xiaomimimo.com/v1",
                    kind="llm",
                ),
                "https://token-plan-sgp.xiaomimimo.com/v1",
            )

    def test_provider_policy_rejects_ssrf_destinations_and_redirect_inputs(self):
        for url in (
            "http://169.254.169.254/latest/meta-data",
            "http://127.0.0.1:8188/?next=http://attacker",
            "https://user:password@token-plan-sgp.xiaomimimo.com/v1",
            "https://attacker.example/v1",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_provider_url(url, kind="llm", resolve_dns=False)

    def test_provider_list_normalizes_only_safe_worker_urls(self):
        self.assertEqual(
            validate_provider_urls(
                " http://127.0.0.1:8188/ , http://localhost:8189 "
            ),
            "http://127.0.0.1:8188,http://localhost:8189",
        )

    def test_story_id_cannot_select_a_container_or_path(self):
        for story_id in (".", "..", ".trash", "story/other", "story\\other"):
            with self.subTest(story_id=story_id), self.assertRaises(ValueError):
                validate_story_id(story_id)
        self.assertEqual(
            validate_story_id("the-foxs-secret-threshold"),
            "the-foxs-secret-threshold",
        )

    def test_raw_settings_compatibility_response_masks_credentials(self):
        masked = _mask_settings({"llm_api_key": "secret-provider-key"})
        self.assertNotIn("secret-provider-key", masked.values())
        self.assertEqual(masked["llm_api_key"], "secr...-key")

    def test_generated_story_path_rejects_dot_before_filesystem_lookup(self):
        with self.assertRaisesRegex(HTTPException, "single alphanumeric slug"):
            generated_story_dir(".")

    def test_privileged_routes_have_operator_dependencies(self):
        import server

        protected = {
            "/api/settings/raw",
            "/api/generate",
            "/api/comfyui/workers/spawn-gpu",
            "/api/system/restart",
            "/api/generated-stories/{story_id}/run-critic",
        }
        for route in server.app.routes:
            if getattr(route, "path", None) in protected:
                self.assertTrue(route.dependant.dependencies, route.path)


if __name__ == "__main__":
    unittest.main()
