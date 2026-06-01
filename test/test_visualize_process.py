import os
import threading

import pytest

from marimapper.visualize_process import (
    VisualiseProcess,
    should_force_xwayland,
    force_xwayland_if_useful,
)


@pytest.fixture(autouse=True)
def _preserve_display_env():
    """run() mutates os.environ (pops WAYLAND_DISPLAY) in production; the tests
    drive run() in-process, so snapshot and restore the display vars to keep
    the pytest session's environment pristine."""
    saved = {k: os.environ.get(k) for k in ("WAYLAND_DISPLAY", "DISPLAY")}
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.mark.parametrize(
    "environ,expected",
    [
        ({"WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":1"}, True),
        ({"WAYLAND_DISPLAY": "wayland-1"}, False),
        ({"DISPLAY": ":1"}, False),
        ({}, False),
        ({"WAYLAND_DISPLAY": "", "DISPLAY": ":1"}, False),
    ],
)
def test_should_force_xwayland(environ, expected):
    assert should_force_xwayland(environ) is expected


def test_force_xwayland_pops_wayland_display_when_xwayland_available():
    environ = {"WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":1"}
    assert force_xwayland_if_useful(environ) is True
    assert "WAYLAND_DISPLAY" not in environ
    assert environ["DISPLAY"] == ":1"


def test_force_xwayland_noop_without_display():
    environ = {"WAYLAND_DISPLAY": "wayland-1"}
    assert force_xwayland_if_useful(environ) is False
    assert environ == {"WAYLAND_DISPLAY": "wayland-1"}


def test_force_xwayland_noop_on_empty_env():
    environ = {}
    assert force_xwayland_if_useful(environ) is False
    assert environ == {}


class _FakeViewControl:
    def set_up(self, *a):
        pass

    def set_lookat(self, *a):
        pass

    def set_zoom(self, *a):
        pass

    def set_constant_z_far(self, *a):
        pass


class _FakeRenderOptions:
    pass


class _FakeVisualizer:
    """Stand-in for open3d.visualization.Visualizer that never opens a real
    window. ``create_ok`` controls what create_window() reports."""

    def __init__(self, create_ok):
        self._create_ok = create_ok

    def create_window(self, **kwargs):
        return self._create_ok

    def get_view_control(self):
        return _FakeViewControl()

    def get_render_option(self):
        return _FakeRenderOptions()


def test_initialise_visualiser_raises_when_create_window_fails(monkeypatch):
    import open3d

    monkeypatch.setattr(
        open3d.visualization, "Visualizer", lambda: _FakeVisualizer(create_ok=False)
    )

    proc = VisualiseProcess()
    with pytest.raises(Exception):
        proc.initialise_visualiser__()


def test_initialise_visualiser_succeeds_when_create_window_ok(monkeypatch):
    import open3d

    monkeypatch.setattr(
        open3d.visualization, "Visualizer", lambda: _FakeVisualizer(create_ok=True)
    )

    proc = VisualiseProcess()
    proc.initialise_visualiser__()  # must not raise


def test_run_survives_visualiser_init_failure():
    """If open3d cannot create a window (e.g. Wayland/GLFW issue), the
    visualiser process must stay alive so the rest of the scan keeps running.
    Scanner.check_for_crash() treats a dead VisualiseProcess as a fatal
    error, so the process needs to drain its queue rather than raise."""

    proc = VisualiseProcess()

    def boom():
        raise RuntimeError("simulated GLFW/Wayland failure")

    proc.initialise_visualiser__ = boom

    proc.get_input_queue().put([object()] * 9)

    threading.Timer(0.5, proc.stop).start()

    proc.run()


def test_run_reroutes_through_xwayland(monkeypatch):
    """On a Wayland session with XWayland available, run() must pop
    WAYLAND_DISPLAY before initialising so GLFW falls back to X11."""
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("DISPLAY", ":1")

    proc = VisualiseProcess()

    def boom():
        raise RuntimeError("simulated GLFW/Wayland failure")

    proc.initialise_visualiser__ = boom

    proc.get_input_queue().put([object()] * 9)

    threading.Timer(0.5, proc.stop).start()

    proc.run()

    assert "WAYLAND_DISPLAY" not in os.environ
