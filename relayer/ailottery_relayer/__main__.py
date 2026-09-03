"""CLI: `python -m ailottery_relayer [run|once|status|serve]`.

  run     (default) start the HTTP API and drive rounds forever
  once    drive exactly one round and exit (handy for CI / smoke tests)
  status  print the current economy snapshot as JSON and exit
  serve   start only the HTTP API (no round driving)
"""
from __future__ import annotations

import json
import sys
import threading
import time

import uvicorn

from .config import Config
from .economy import EconomyEngine
from .log import get_logger
from .server import make_app

log = get_logger("main")


def _wait_for_address(cfg: Config, timeout: float = 180.0) -> None:
    """Block until the deploy step has written the address (docker compose ordering)."""
    start = time.time()
    while time.time() - start < timeout:
        if cfg.resolved_address():
            return
        log.info("waiting for lottery address (%s)…", cfg.address_file)
        time.sleep(2)
    raise SystemExit("timed out waiting for the lottery address")


def _serve(engine: EconomyEngine) -> threading.Thread:
    app = make_app(engine)
    cfg = engine.cfg
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.serve_host, port=cfg.serve_port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    log.info("relayer API on http://%s:%s (GET /economy, POST /voucher)", cfg.serve_host, cfg.serve_port)
    return t


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    cfg = Config.from_env()
    log.info("AI-Agent Oracle Lottery relayer — mode=%s cmd=%s", cfg.mode, cmd)
    _wait_for_address(cfg)
    engine = EconomyEngine(cfg)

    if cmd == "status":
        print(json.dumps(engine.snapshot(), indent=2, default=str))
        return
    if cmd == "once":
        engine.run_one_round()
        print(json.dumps(engine.snapshot(), indent=2, default=str))
        return
    if cmd == "serve":
        _serve(engine)
        while True:
            time.sleep(3600)

    # run: API + forever loop
    _serve(engine)
    try:
        engine.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()


if __name__ == "__main__":
    main()
