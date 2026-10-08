"""Keep child processes from opening console windows on the Windows desktop.

The desktop backend starts console programs constantly: PowerShell for every
workspace command, npm and node beneath it, taskkill, git, the analysis
sandbox. Without CREATE_NO_WINDOW, Windows may give each one a console window
of its own, and a build then flashes a stream of terminals across the
user's screen, outside the app.

Applied once, process-wide, as a default on subprocess.Popen, so every current
and future call site is covered, including those inside third-party libraries.
A child started this way gets a console with no window, and its own console
children inherit that invisible console, so the whole tree stays hidden.
"""
from __future__ import annotations

import os
import subprocess

_installed = False


def hide_child_consoles() -> None:
    global _installed
    if _installed or os.name != "nt":
        return
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    original_init = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):  # noqa: N807 - wraps Popen.__init__
        flags = kwargs.get("creationflags", 0) or 0
        # A caller asking for a NEW console wants one; leave it alone.
        if not flags & getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010):
            kwargs["creationflags"] = flags | flag
        original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__
    _installed = True
