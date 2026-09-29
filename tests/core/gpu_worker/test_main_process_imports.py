from __future__ import annotations

import json
import os
import subprocess
import sys

from core.config import BASE_DIR
from core.gpu_worker.protocol import DISABLED_ENV

_PROBE = """
import json
import sys
import threading

import core.main

for thread in threading.enumerate():
    if thread.name in ("command-classifier-warmup", "semantic-matcher-warmup"):
        thread.join(60)

print(json.dumps({name: name in sys.modules for name in ("torch", "sentence_transformers", "transformers")}))
"""


def test_main_process_never_imports_torch() -> None:
    env = dict(os.environ)
    env[DISABLED_ENV] = "1"
    env["ASSISTANT_VOICE_AUTOSTART"] = "false"

    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(BASE_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )

    loaded = json.loads(completed.stdout.strip().splitlines()[-1])
    assert loaded == {"torch": False, "sentence_transformers": False, "transformers": False}
