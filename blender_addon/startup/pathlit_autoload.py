"""Pathlit autoload: turns the Pathlit Bridge add-on on every time Blender starts, without the Preferences checkbox.
It does not write to your Blender preferences (default_set=False). Remove with: python scripts/install_addon.py --remove
"""
import bpy


def _enable():
    import addon_utils
    try:
        addon_utils.enable("pathlit_bridge", default_set=False, persistent=True)
    except Exception as e:
        print("[pathlit_autoload] could not enable pathlit_bridge:", e)
    return None


def register():
    bpy.app.timers.register(_enable, first_interval=1.0)


def unregister():
    pass
