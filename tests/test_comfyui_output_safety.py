import pytest

from comfyui_utils import _history_error_message, _safe_output_filename


def test_comfy_filename_is_reduced_to_a_safe_leaf():
    assert _safe_output_filename("nested\\scene:01?.png") == "scene_01_.png"


def test_comfy_history_exposes_provider_failure_reason():
    assert "not enough GPU" in _history_error_message({
        "status_str": "error",
        "messages": [["execution_error", {"exception_message": "not enough GPU memory"}]],
    })


@pytest.mark.parametrize("filename", ["", ".", "..", "\\", "/"])
def test_comfy_filename_rejects_empty_leaf(filename):
    with pytest.raises(ValueError):
        _safe_output_filename(filename)
