"""Asks the Blender add-on for the current state, on demand (FR-10). Any failure returns None and never crashes."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from .models import BlenderState

log = logging.getLogger(__name__)


class BlenderBridge:
    def __init__(self, port: int = 8765, timeout_s: float = 1.0, host: str = "127.0.0.1") -> None:
        self.base = f"http://{host}:{port}"
        self.timeout = timeout_s
        self._was_up: bool | None = None
        self.last_error: str | None = None

    def _get(self, path: str) -> str:
        with urllib.request.urlopen(f"{self.base}{path}", timeout=self.timeout) as r:
            return r.read().decode("utf-8")

    def ping(self) -> bool:
        try:
            return self._get("/ping") == "ok"
        except Exception:
            return False

    REQUIRED_API = 2

    def api_version(self) -> int | None:
        """The add-on's API version: 2+ can run actions, 1 is an old read-only copy, None = Blender is not reachable."""
        try:
            return int(json.loads(self._get("/version"))["api"])
        except urllib.error.HTTPError:
            return 1 if self.ping() else None                    # an old add-on has no /version
        except Exception:
            return 1 if self.ping() else None

    def do(self, action: str, args: dict, timeout_s: float = 10.0) -> dict:
        """Ask the add-on to run ONE allow-listed action. Returns {"ok": bool, ...}; never raises."""
        data = json.dumps({"action": action, "args": args}).encode("utf-8")
        req = urllib.request.Request(f"{self.base}/do", data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:                       # 400 refused / 422 failed: the body says why
            if e.code in (404, 501):                              # an old add-on: it does not know POST /do
                return {"ok": False, "error": "The Blender add-on is out of date. Run  pathlit blender  and then restart Blender.", "outdated": True}
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                return {"ok": False, "error": f"HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}

    def get_state(self) -> BlenderState | None:
        try:
            state = BlenderState.model_validate(json.loads(self._get("/state")))
            self.last_error = None
            if self._was_up is False:
                log.info("blender link is back")
            self._was_up = True
            return state
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"[:200]
            if self._was_up is not False:                  # log once per outage, not on every press
                log.warning("blender link unavailable (%s); using screen-only checks", self.last_error)
            self._was_up = False
            return None
