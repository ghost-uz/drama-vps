"""Pleyer audio-trek mantig'i (static/js/player-core.js) — Node testi [audio-track].

Repoda JS test-infratuzilmasi yo'q: mantiq `jstests/player_core_audio.test.mjs`
da Node'ning o'rnatilgan `node --test` runner'i bilan (bog'liqliksiz) sinaladi,
bu yerda esa pytest orqali ishga tushiriladi — CI'ning yagona test job'i shu.
GitHub runner'larida Node oldindan o'rnatilgan; topilmasa (masalan Docker
ichida) test SKIP bo'ladi.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS_TEST = ROOT / "jstests" / "player_core_audio.test.mjs"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node o'rnatilmagan")
def test_player_core_audio_tracks():
    proc = subprocess.run(
        [NODE, "--test", str(JS_TEST)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
