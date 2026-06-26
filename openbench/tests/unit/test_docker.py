"""Unit tests for the docker-out-of-docker host-path translation."""

from __future__ import annotations

import unittest
from unittest import mock

from openbench import docker


class HostSourceTests(unittest.TestCase):
    def _patch_mounts(self, mounts: tuple[tuple[str, str], ...]) -> object:
        return mock.patch("openbench.docker._self_bind_mounts", return_value=mounts)

    def test_host_mode_returns_path_unchanged(self) -> None:
        with self._patch_mounts(()):
            self.assertEqual(docker.host_source("/repo/openbench/probes"), "/repo/openbench/probes")

    def test_translates_path_under_mount(self) -> None:
        with self._patch_mounts((("/workspace", "/host/repo"),)):
            self.assertEqual(
                docker.host_source("/workspace/openbench/probes"), "/host/repo/openbench/probes"
            )

    def test_mount_root_maps_to_source(self) -> None:
        with self._patch_mounts((("/workspace", "/host/repo"),)):
            self.assertEqual(docker.host_source("/workspace"), "/host/repo")

    def test_path_outside_any_mount_is_unchanged(self) -> None:
        with self._patch_mounts((("/workspace", "/host/repo"),)):
            self.assertEqual(docker.host_source("/elsewhere/x"), "/elsewhere/x")

    def test_docker_desktop_style_source(self) -> None:
        source = "/run/desktop/mnt/host/c/Users/me/repo"
        with self._patch_mounts((("/workspace", source),)):
            self.assertEqual(
                docker.host_source("/workspace/.openbench/cfg.toml"),
                f"{source}/.openbench/cfg.toml",
            )

    def test_most_specific_mount_wins(self) -> None:
        mounts = (("/workspace/sub", "/host/sub"), ("/workspace", "/host/repo"))
        with self._patch_mounts(mounts):
            self.assertEqual(docker.host_source("/workspace/sub/x"), "/host/sub/x")

    def test_mount_string_uses_host_source(self) -> None:
        with self._patch_mounts((("/workspace", "/host/repo"),)):
            self.assertEqual(
                docker.mount("/workspace/probes", "/probes"), "/host/repo/probes:/probes:ro"
            )
            self.assertEqual(
                docker.mount("/workspace/probes", "/probes", read_only=False),
                "/host/repo/probes:/probes",
            )
