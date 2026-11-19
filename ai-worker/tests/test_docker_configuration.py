"""Static checks of the optional OpenVINO Docker integration (quantization Phase 2).

These read compose.yaml and the worker Dockerfile as text (no YAML library is a project dependency);
they do not build images or start containers.
"""

from __future__ import annotations

from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]
PYTHON_SERVICES = ("ai-worker", "ai-detection-consumer", "ai-live-worker")
COMPOSE = (REPO / "compose.yaml").read_text(encoding="utf-8")


def service_block(name: str) -> str:
    """The text of one top-level service (two-space indent under ``services:``)."""
    services = COMPOSE.split("\nservices:\n", 1)[1]
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|^\S|\Z)", services, flags=re.MULTILINE | re.DOTALL)
    assert match, f"service {name} not found"
    return match.group(1)


def shared_ai_environment() -> str:
    return COMPOSE.split("x-ai-environment: &ai-environment\n", 1)[1].split("\n\n", 1)[0]


def test_every_python_service_builds_without_openvino_by_default() -> None:
    for name in PYTHON_SERVICES:
        assert "INSTALL_OPENVINO: ${AI_WORKER_INSTALL_OPENVINO:-false}" in service_block(name), name


def test_inference_services_default_to_fp32_with_fallback_and_a_persistent_artifact_dir() -> None:
    assert "*ai-environment" in service_block("ai-detection-consumer")
    for name, environment in (("ai-detection-consumer", shared_ai_environment()),
                              ("ai-live-worker", service_block("ai-live-worker"))):
        assert "AI_MODEL_PRECISION: ${AI_MODEL_PRECISION:-fp32}" in environment, name
        assert "AI_INT8_FALLBACK_TO_FP32: ${AI_INT8_FALLBACK_TO_FP32:-true}" in environment, name
        assert "AI_QUANTIZED_MODEL_DIR: /data/models/quantized" in environment, name
        # The artifact directory lives in the persistent named model-cache volume.
        assert re.search(r"- ai-model-cache:/data/models(:ro)?\n", service_block(name)), name


def test_no_service_exports_int8_models_on_startup() -> None:
    for name in PYTHON_SERVICES:
        command = re.search(r"^    command: (.*)$", service_block(name), flags=re.MULTILINE)
        assert command is None or "quantize" not in command.group(1), name


def test_dockerfile_adds_openvino_only_behind_the_build_argument() -> None:
    dockerfile = (REPO / "ai-worker" / "Dockerfile").read_text(encoding="utf-8")
    cpu_stage = dockerfile.split("FROM runtime AS cpu", 1)[1]

    assert "ARG INSTALL_OPENVINO=false" in cpu_stage
    base_install = cpu_stage.index("pip install --no-cache-dir -r requirements-ai.txt")
    optional_install = cpu_stage.index("-r requirements-quantization.txt")
    # The optional layer comes after the PyTorch layer, so default builds keep their cached layers.
    assert base_install < cpu_stage.index("ARG INSTALL_OPENVINO") < optional_install
    assert re.search(r'if \[ "\$INSTALL_OPENVINO" = "true" \]', cpu_stage)


def test_quantization_requirements_are_pinned_and_artifacts_stay_out_of_the_image() -> None:
    requirements = (REPO / "ai-worker" / "requirements-quantization.txt").read_text(encoding="utf-8")
    pins = dict(re.findall(r"^([a-z0-9-]+)==(\S+)$", requirements, flags=re.MULTILINE))
    assert set(pins) == {"openvino", "nncf"}
    ignored = (REPO / "ai-worker" / ".dockerignore").read_text(encoding="utf-8").split()
    assert "model-cache/" in ignored and "*.pt" in ignored


def test_env_example_documents_fp32_defaults() -> None:
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    assert "AI_MODEL_PRECISION=fp32" in example
    assert "AI_WORKER_INSTALL_OPENVINO=false" in example
    assert "AI_INT8_FALLBACK_TO_FP32=true" in example
