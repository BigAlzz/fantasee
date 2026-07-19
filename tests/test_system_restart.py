from fantasee_server.api import system


def test_restart_plan_has_one_server_and_the_requested_worker_stack():
    assert [service["port"] for service in system._mode_plan("basic")] == [8765, 8189]
    assert [service["port"] for service in system._mode_plan("gpu")] == [8765, 8188]
    assert [service["port"] for service in system._mode_plan("max")] == [8765, 8188, 8189]


def test_restart_server_environment_is_explicit_and_duplicate_safe():
    env = system._server_environment("max")
    assert env["FANTASEE_RENDERING_MODE"] == "max"
    assert env["FANTASEE_AUTO_SPAWN_CPU"] == "0"
    assert env["COMFYUI_URLS"] == "http://127.0.0.1:8188,http://127.0.0.1:8189"
