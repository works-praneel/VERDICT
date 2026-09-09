"""Focused Phase 2 Step 3 tests for Dockerfile base-image pinning."""
import pytest

from verdict.evidence import docker_base_image_pinning_to_evidence
from verdict.tool_registry import ToolRegistry
from verdict.tools import check_container_base_image_pinning


def test_untagged_docker_base_image_is_detected():
    findings = check_container_base_image_pinning(
        "+++ b/Dockerfile\n@@ -0,0 +1 @@\n+FROM python", ["Dockerfile"]
    )

    assert findings == [{"file": "Dockerfile", "line": 1, "image": "python", "reason": "untagged"}]


def test_latest_docker_base_image_is_detected():
    findings = check_container_base_image_pinning(
        "+++ b/Dockerfile\n@@ -0,0 +1 @@\n+FROM nginx:latest", ["Dockerfile"]
    )

    assert findings[0]["image"] == "nginx:latest"
    assert findings[0]["reason"] == "latest"


@pytest.mark.parametrize("image", ["python:3.12", "ubuntu:24.04"])
def test_version_tagged_docker_base_images_are_not_detected(image):
    assert check_container_base_image_pinning(
        f"+++ b/Dockerfile\n@@ -0,0 +1 @@\n+FROM {image}", ["Dockerfile"]
    ) == []


def test_clean_docker_diff_produces_no_evidence():
    assert docker_base_image_pinning_to_evidence(
        check_container_base_image_pinning("+++ b/Dockerfile\n@@ -0,0 +1 @@\n+RUN echo ready", ["Dockerfile"])
    ) == []


def test_docker_capability_resolves_and_normalizes_source_attributed_evidence():
    registry = ToolRegistry()
    resolution = registry.resolve(["check_container_base_image_pinning"])
    execution = registry.execute(
        resolution,
        "repo",
        ["Dockerfile"],
        "+++ b/Dockerfile\n@@ -0,0 +1 @@\n+FROM python",
    )

    assert [registration.tool_name for registration in resolution.supported] == [
        "check_container_base_image_pinning"
    ]
    assert execution.raw_results["check_container_base_image_pinning"][0]["image"] == "python"
    assert execution.evidence == [
        {
            "capability": "check_container_base_image_pinning",
            "tool": "check_container_base_image_pinning",
            "kind": "container",
            "file": "Dockerfile",
            "line": 1,
            "message": "Base image 'python' is untagged.",
            "severity": "info",
            "rule_id": "docker_base_image_not_pinned",
            "details": {"image": "python", "reason": "untagged"},
        }
    ]
