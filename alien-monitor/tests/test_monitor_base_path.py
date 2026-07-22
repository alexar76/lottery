from monitor_base_path import strip_monitor_prefix


def test_strip_monitor_api_prefix():
    assert strip_monitor_prefix("/monitor/api/health") == "/api/health"
    assert strip_monitor_prefix("/monitor/api/state") == "/api/state"


def test_strip_monitor_ws_prefix():
    assert strip_monitor_prefix("/monitor/ws") == "/ws"
    assert strip_monitor_prefix("/monitor/ws/extra") == "/ws/extra"


def test_strip_monitor_prefix_ignores_assets():
    assert strip_monitor_prefix("/monitor/assets/app.js") is None
    assert strip_monitor_prefix("/monitor/") is None
