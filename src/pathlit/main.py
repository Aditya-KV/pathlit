"""Starts everything: the overlay pointer, the control panel, the hotkey and the click listener."""
from __future__ import annotations

import logging
import sys
import threading

from .activity import ActivityListener, make_foreground_check
from .capture import grab_main_monitor, make_dpi_aware
from .config import ROOT, env, load_settings
from .controller import Controller
from .hotkeys import HotkeyListener
from .logging_utils import SessionCsv, setup_logging


def _single_instance():
    """Two copies would both listen to the hotkey, draw two overlays and talk over each other. Refuse a second one."""
    if sys.platform != "win32":
        return None
    import ctypes
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\PathlitSingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:          # ERROR_ALREADY_EXISTS
        sys.exit("Pathlit is already running. Close the other copy first (Ctrl+C in its terminal), then start again.")
    return handle                                              # keep the handle alive for the life of the process


def _make_tray(app, set_mode, bridge_ui):
    """Tray icon and menu to switch mode. The icon colour shows the mode (blue Teach me, amber Show me, red Do it)."""
    from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
    from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

    colors = {"teach": "#4f7cff", "show": "#f0a030", "do": "#d83a3a"}
    labels = {"teach": "Teach me (I point, you click)", "show": "Show me (I click, you watch)", "do": "Do it (I do the task)"}

    def icon(mode: str) -> QIcon:
        pm = QPixmap(32, 32)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(colors[mode]))
        p.setPen(QColor("white"))
        p.drawEllipse(3, 3, 26, 26)
        p.end()
        return QIcon(pm)

    tray = QSystemTrayIcon(icon("teach"), app)
    menu = QMenu()
    actions = {}
    for key in ("teach", "show", "do"):
        a = QAction(labels[key], menu)
        a.setCheckable(True)
        a.triggered.connect(lambda _c, k=key: set_mode(k))
        menu.addAction(a)
        actions[key] = a
    menu.addSeparator()
    menu.addAction("Quit Pathlit").triggered.connect(app.quit)

    def on_mode(mode: str) -> None:
        for k, a in actions.items():
            a.setChecked(k == mode)
        tray.setIcon(icon(mode))
        tray.setToolTip("Pathlit: " + labels[mode])

    bridge_ui.mode.connect(on_mode)
    tray.setContextMenu(menu)
    tray.show()
    return tray


def main() -> None:
    _lock = _single_instance()
    make_dpi_aware()                       # must happen before Qt starts
    setup_logging(ROOT / "logs")
    log = logging.getLogger("pathlit")
    settings = load_settings()

    from PyQt6.QtWidgets import QApplication

    from .blender_bridge import BlenderBridge
    from .brain.docs_search import make_docs_search
    from .brain.planner import PlanError, plan_lesson
    from .brain.teacher import make_teacher
    from .lessons.loader import load_all
    from .overlay.window import OverlayWindow
    from .perception.azure_vision import AzureVisionReader
    from .perception.mirage_reader import MirageReader
    from .perception.router import Router
    from .skillmap import SkillMap
    from .ui.panel import PanelBridge, PathlitPanel
    from .voice import AzureSpeaker
    from .activity import foreground_title
    from .control.executor import ActionLog, Autopilot
    from .control.guard import Guard
    from .control.mouse import LazyMover
    from .hotkeys import parse_key

    lessons = load_all(ROOT / settings["lessons_dir"])      # a bad lesson file stops startup with a clear message
    skillmap = SkillMap(ROOT / settings["skillmap_db"])
    app = QApplication(sys.argv)
    overlay = OverlayWindow(arrow_seconds=settings["arrow_seconds"])
    panel = PathlitPanel(settings["hotkey"].upper())
    bridge_ui = PanelBridge()
    bridge_ui.state.connect(panel.show_state)
    bridge_ui.status.connect(panel.set_status)
    bridge_ui.busy.connect(panel.set_busy)
    router = Router(AzureVisionReader(max_edge=settings["vision_max_edge"]),
                    MirageReader() if settings.get("mirage_fallback") else None)
    speaker = AzureSpeaker(voice=settings["voice"])
    blender = BlenderBridge(settings["blender_port"], settings["blender_timeout_s"])
    teacher = make_teacher(settings["provider"], None, None, settings["teacher_timeout_s"], settings["session_token_cap"],
                           ROOT / "logs" / "prompts.jsonl")
    docs = make_docs_search()
    csv = SessionCsv(ROOT / settings["session_csv"])
    controller = Controller(lessons, skillmap, grab_main_monitor, router, blender, teacher, docs, speaker, overlay, csv,
                            match_min=settings["match_min"], docs_top_k=settings["docs_top_k"],
                            auto_advance=settings["auto_advance"], settle_s=settings["auto_settle_s"],
                            idle_hint_s=settings["idle_hint_s"], second_look_s=settings["second_look_s"],
                            fast_settle_s=settings["fast_settle_s"], on_state=bridge_ui.state.emit,
                            foreground_ok=make_foreground_check(settings["auto_window_title"]))

    # ---- Show me / Do it (cursor control). Created now, but the mouse library loads only if you use those modes ----
    mover = LazyMover()
    guard = Guard(settings["allowed_apps"], foreground_title, mover.position, abort_px=settings["mouse_abort_px"],
                  max_actions=settings["max_actions_per_task"])
    autopilot = Autopilot(grab=grab_main_monitor, reader=router, bridge=blender, overlay=overlay, speaker=speaker,
                          skillmap=skillmap, lessons=lessons, guard=guard, mover=mover,
                          action_log=ActionLog(ROOT / "logs" / "actions.csv"), foreground_title=foreground_title,
                          match_min=settings["match_min"], action_delay_s=settings["action_delay_s"],
                          move_s=settings["mouse_move_s"], on_state=bridge_ui.state.emit)
    controller.autopilot = autopilot

    def set_mode(mode: str) -> None:
        if mode not in ("teach", "show", "do"):
            return
        if autopilot.running:
            autopilot.stop("You changed the mode, so I stopped.")
        controller.mode = mode
        bridge_ui.mode.emit(mode)
        log.info("mode=%s", mode)

    bridge_ui.mode.connect(panel.set_mode)
    panel.mode_requested.connect(set_mode)
    set_mode(settings["mode"])

    def on_escape() -> None:
        """FR-24: Esc stops all cursor movement and speech at once, in every mode."""
        autopilot.stop("Stopped.")
        speaker.stop()
        overlay.clear()

    # ---- "I want to make ...": plan the steps with the model, check them, queue them ----
    def plan(goal: str) -> None:
        def work() -> None:
            bridge_ui.busy.emit(True)
            try:
                res = plan_lesson(teacher.client, teacher.large, goal, settings["plan_timeout_s"],
                                  on_wait=lambda w: bridge_ui.status.emit(
                                      f"The free model is busy; waiting {w:.0f} s, then I will check the geometry..."))
                controller.queue_lesson(res.lesson)
                note = f"Planned {len(res.lesson.steps)} steps."
                if res.uses_default_scene:
                    note += " Start from Blender's default scene (a cube, a camera and a light)."
                if res.warnings:
                    note += " Check: " + "; ".join(res.warnings) + "."
                if res.compound_steps:
                    note += f" {res.compound_steps} step(s) combine several actions; do them in order."
                if res.unverified_labels:
                    note += " Labels I have not seen on a real Blender screen: " + ", ".join(res.unverified_labels) + "."
                bridge_ui.status.emit(note + f" Press {settings['hotkey'].upper()} to begin.")
                speaker.speak(f"Here is the plan for {res.lesson.title}. {len(res.lesson.steps)} steps. "
                              f"Press {settings['hotkey'].upper()} when you are ready.")
            except PlanError as e:
                bridge_ui.status.emit(str(e))
            except Exception as e:                          # planning must never crash the app
                log.exception("planning failed")
                bridge_ui.status.emit(f"Planning failed: {str(e)[:120]}")
            finally:
                bridge_ui.busy.emit(False)
        threading.Thread(target=work, daemon=True).start()

    panel.plan_requested.connect(plan)
    panel.start_requested.connect(controller.on_hotkey)

    def warm() -> None:
        router.warm_up()
        speaker.warm_up()
        nxt = skillmap.next_lesson(lessons)
        if nxt:                                             # show the next built-in lesson's steps in the panel
            bridge_ui.state.emit({"title": nxt.title, "steps": [s.instruction for s in nxt.steps], "index": -1,
                                  "complete": False, "custom": False})
        print("\n=== Pathlit ready ===")
        print(f"Lessons loaded : {len(lessons)}   next lesson: {nxt.title if nxt else 'all done'}")
        api = blender.api_version()
        print(f"Blender link   : {'connected' if api is not None else 'NOT connected (screen-only checks)'}")
        if api is not None and api < blender.REQUIRED_API:
            print("                 !! The Blender add-on is OUT OF DATE. Run  pathlit blender  and restart Blender,")
            print("                 !! or Show me / Do it and numeric checks will not work.")
        print(f"Teacher model  : {'Groq' if teacher.client else 'off (lesson text only; typed tasks need Groq)'}")
        print(f"Manual search  : {'Azure AI Search' if type(docs).__name__ == 'AzureDocsSearch' else 'off'}")
        if settings["auto_advance"]:
            print(f"Auto-advance   : ON. Press {settings['hotkey'].upper()} once to start; after that it follows your clicks "
                  f"in '{settings['auto_window_title']}' windows only.")
        print(f"Press {settings['hotkey'].upper()} to start a lesson, or any time to check and explain. "
              "Ctrl+C in this window to quit.\n")

    threading.Thread(target=warm, daemon=True).start()
    hotkey = HotkeyListener(settings["hotkey"], controller.on_hotkey)
    hotkey.start()
    HotkeyListener(settings["stop_key"], on_escape).start()
    if settings["auto_advance"]:
        ActivityListener(controller.on_activity, ignore_keys=(hotkey._key, parse_key(settings["stop_key"]))).start()
    if env("DEBUG_SAVE_SCREENS").lower() == "true":
        log.warning("DEBUG_SAVE_SCREENS is on")
    panel.show()
    tray = _make_tray(app, set_mode, bridge_ui)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
