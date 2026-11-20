"""FR-10: the Blender add-on's state server and the app's client. Uses a fake bpy, so no Blender is needed."""
import importlib.util
import socket
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from pathlit.blender_bridge import BlenderBridge

ADDON = Path(__file__).resolve().parents[1] / "blender_addon" / "pathlit_bridge" / "__init__.py"


def _load_addon():
    spec = importlib.util.spec_from_file_location("pathlit_bridge_under_test", ADDON)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _fake_bpy(mode="OBJECT", modifiers=("SUBSURF",)):
    obj = NS(name="Torus", type="MESH", modifiers=[NS(type=m) for m in modifiers])
    ctx = NS(mode=mode, view_layer=NS(objects=NS(active=obj)), selected_objects=[obj], scene=NS(objects=[obj, obj, obj]))
    return NS(context=ctx, app=NS(version=(4, 1, 1)))


def test_fr10_addon_builds_state_in_the_spec_shape():
    addon = _load_addon()
    st = addon.build_state(_fake_bpy("EDIT_MESH"))
    assert st == {"blender_version": "4.1.1", "mode": "EDIT_MESH",
                  "active_object": {"name": "Torus", "type": "MESH", "modifiers": ["SUBSURF"]},
                  "selected_count": 1, "object_count": 3}


def test_fr10_addon_handles_no_active_object():
    addon = _load_addon()
    fake = _fake_bpy()
    fake.context.view_layer.objects.active = None
    assert addon.build_state(fake)["active_object"] is None


def test_fr10_server_listens_on_localhost_only_and_client_reads_state():
    addon = _load_addon()
    port = _free_port()
    addon._cache["state"] = addon.build_state(_fake_bpy())
    addon.start_server(port)
    try:
        assert addon._server.server_address[0] == "127.0.0.1"
        bridge = BlenderBridge(port=port, timeout_s=1)
        assert bridge.ping()
        st = bridge.get_state()
        assert st and st.mode == "OBJECT" and st.active_object.modifiers == ["SUBSURF"] and st.object_count == 3
    finally:
        addon.stop_server()


def test_fr10_state_before_first_refresh_is_a_clean_none_not_a_crash():
    addon = _load_addon()
    port = _free_port()
    addon._cache["state"] = None
    addon.start_server(port)
    try:
        assert BlenderBridge(port=port, timeout_s=1).get_state() is None
    finally:
        addon.stop_server()


def test_fr10_closing_the_addon_does_not_crash_the_app_and_returns_quickly():
    bridge = BlenderBridge(port=_free_port(), timeout_s=1)       # nothing is listening
    t0 = time.perf_counter()
    assert bridge.get_state() is None
    assert time.perf_counter() - t0 < 1.5          # the 1 second timeout, not longer
    assert bridge.last_error
    assert not bridge.ping()


def test_fr10_garbage_from_the_server_is_rejected_not_trusted():
    addon = _load_addon()
    port = _free_port()
    addon._cache["state"] = {"mode": 123, "nonsense": True}
    addon.start_server(port)
    try:
        assert BlenderBridge(port=port, timeout_s=1).get_state() is None
    finally:
        addon.stop_server()
