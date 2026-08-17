"""Jarvis Blender remote-control addon.

Install via Edit > Preferences > Add-ons > Install..., pick this directory
zipped up (or point Blender's addon path at it directly for development),
then enable "Jarvis Voice Control". While enabled, it runs a local HTTP
server (see server.py) inside Blender's own process that the Jarvis backend
(modules/blender_control/ws_client.py) talks to — no separate process, no
extra dependencies beyond Blender's own bundled Python.
"""

bl_info = {
    "name": "Jarvis Voice Control",
    "author": "Jarvis",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "N/A — background service, no UI panel",
    "description": "Lets the Jarvis voice assistant control Blender (objects, modifiers, materials, render, ...) over a local HTTP connection.",
    "category": "System",
}

from . import server


def register() -> None:
    # Runs the server in a background thread (see server.start()) so
    # Blender's own UI thread is never blocked waiting on it — the server
    # only ever hands work *back* to the main thread via bpy.app.timers,
    # never the other way around.
    server.start()


def unregister() -> None:
    server.stop()


if __name__ == "__main__":
    register()
