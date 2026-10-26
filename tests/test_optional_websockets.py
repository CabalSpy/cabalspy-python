"""The REST client must import without the optional websockets package."""

from __future__ import annotations

import subprocess
import sys
import textwrap


def test_import_and_rest_without_websockets() -> None:
    # A fresh interpreter in which "import websockets" fails, as after a plain
    # `pip install cabalspy` without the [realtime] extra.
    code = textwrap.dedent(
        """
        import asyncio, builtins
        real_import = builtins.__import__
        def no_websockets(name, *args, **kwargs):
            if name == "websockets" or name.startswith("websockets."):
                raise ImportError("No module named 'websockets'")
            return real_import(name, *args, **kwargs)
        builtins.__import__ = no_websockets

        import cabalspy
        client = cabalspy.CabalSpy("k")
        assert client.calls is not None
        rt = client.realtime()
        try:
            asyncio.run(rt.connect())
        except cabalspy.CabalSpyError as err:
            assert err.code == "missing_dependency", err.code
            assert "cabalspy[realtime]" in str(err)
            print("ok")
        """
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"
