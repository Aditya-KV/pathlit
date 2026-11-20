"""Pathlit Bridge: a Blender add-on that serves the current state on 127.0.0.1 (SRS 9, FR-10) and runs a short allow-list of actions.

- Uses only bpy and the standard library (no installs).
- GET requests only read. Only POST /do can change the scene, and only with an allow-listed action.
- Blender data is read on Blender's main thread by a bpy.app.timers callback every 0.5 s into a cache.
  The HTTP thread only reads the cache.
- GET /state -> JSON (SRS 8.3), GET /ping -> "ok". Bound to 127.0.0.1 only, never 0.0.0.0.
- POST /do runs ONE action from a fixed allow-list (actions.py) on Blender's main thread. The request is plain data and is
  validated again here; nothing from it is ever passed to exec or eval. This is the only part that changes the scene.
"""
bl_info = {
    "name": "Pathlit Bridge",
    "author": "Pathlit",
    "version": (0, 1, 0),
    "blender": (4, 1, 0),
    "location": "Runs in the background",
    "description": "Shares the current mode, active object and modifiers with Pathlit on this computer, and runs a short allow-list of actions when Pathlit's Do it mode asks.",
    "category": "System",
}

import json
import math
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import bpy
except ImportError:          # lets the logic be unit tested outside Blender
    bpy = None

try:
    from . import actions
except ImportError:                        # loaded outside a package (unit tests): load the sibling file directly
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("pathlit_bridge_actions", os.path.join(os.path.dirname(__file__), "actions.py"))
    actions = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(actions)

API_VERSION = 2                            # 1 = read-only state; 2 = also accepts POST /do (allow-listed actions)
HOST = "127.0.0.1"
PORT = int(os.environ.get("PATHLIT_PORT", "8765"))
REFRESH_S = 0.5

_cache = {"state": None}
_jobs = queue.Queue()                      # (action, args, done_event, result) waiting for the main thread
PUMP_S = 0.05
MAX_BODY = 4096
_server = None
_thread = None


def build_state(bpy_module=None):
    """Read the state. MUST run on Blender's main thread (the timer does this)."""
    b = bpy_module or bpy
    ctx = b.context
    obj = ctx.view_layer.objects.active
    try:
        mode = ctx.mode
    except Exception:
        mode = "OBJECT"
    active = None
    if obj is not None:
        active = {"name": obj.name, "type": obj.type, "modifiers": [m.type for m in getattr(obj, "modifiers", [])]}
        try:                                       # where it is, how it is turned, how big (read-only; missing on odd objects)
            active["location"] = [round(float(v), 4) for v in obj.location]
            active["rotation"] = [round(math.degrees(float(v)), 3) for v in obj.rotation_euler]
            active["scale"] = [round(float(v), 4) for v in obj.scale]
            active["dimensions"] = [round(float(v), 4) for v in obj.dimensions]
        except Exception:
            pass
    return {
        "blender_version": ".".join(str(n) for n in b.app.version),
        "mode": mode,
        "active_object": active,
        "selected_count": len(ctx.selected_objects),
        "object_count": len(ctx.scene.objects),
    }


def _refresh():
    try:
        _cache["state"] = build_state()
    except Exception as e:                      # never break Blender because of the bridge
        _cache["state"] = None
        print(f"[pathlit_bridge] state read failed: {e}")
    return REFRESH_S


def _pump():
    """Runs on Blender's main thread (bpy.app.timers). Executes queued /do jobs."""
    while True:
        try:
            action, args, done, result = _jobs.get_nowait()
        except queue.Empty:
            break
        try:
            result["detail"] = actions.run(bpy, action, args)
            result["ok"] = True
        except Exception as e:             # a refused or failed action must never break Blender
            result["ok"] = False
            result["error"] = str(e)[:200]
        try:                               # refresh the cached state NOW, so the step check that follows sees this change
            _cache["state"] = build_state()
        except Exception:
            pass
        done.set()
    return PUMP_S


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):               # keep Blender's console quiet
        pass

    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/do":
            self._send(404, "not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("bad length")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            action = str(body["action"])
            args = actions.validate(action, body.get("args"))
        except (ValueError, KeyError, TypeError, actions.Refused) as e:
            self._send(400, json.dumps({"ok": False, "error": "refused: %s" % str(e)[:120]}), "application/json")
            return
        done, result = threading.Event(), {}
        _jobs.put((action, args, done, result))
        if not done.wait(8.0):
            self._send(504, json.dumps({"ok": False, "error": "Blender did not answer in time"}), "application/json")
            return
        self._send(200 if result.get("ok") else 422, json.dumps(result), "application/json")

    def do_GET(self):
        if self.path == "/ping":
            self._send(200, "ok", "text/plain")
        elif self.path == "/version":
            self._send(200, json.dumps({"api": API_VERSION}), "application/json")
        elif self.path == "/state":
            state = _cache["state"]
            if state is None:
                self._send(503, json.dumps({"error": "no state yet"}), "application/json")
            else:
                self._send(200, json.dumps(state), "application/json")
        else:
            self._send(404, "not found", "text/plain")


def start_server(port=None):
    global _server, _thread
    if _server is not None:
        return
    _server = ThreadingHTTPServer((HOST, port or PORT), _Handler)
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()


def stop_server():
    global _server, _thread
    if _server is not None:
        _server.shutdown()
        _server.server_close()
    _server = _thread = None


def register():
    start_server()
    if bpy is not None and not bpy.app.timers.is_registered(_refresh):
        bpy.app.timers.register(_refresh, first_interval=0.0, persistent=True)
    if bpy is not None and not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=0.0, persistent=True)


def unregister():
    if bpy is not None and bpy.app.timers.is_registered(_refresh):
        bpy.app.timers.unregister(_refresh)
    if bpy is not None and bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)
    stop_server()
    _cache["state"] = None
