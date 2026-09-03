#!/usr/bin/env python3
"""
Capture UNI-mode screenshots + demo video for alien-monitor README.

Outputs:
  docs/screenshots/09-uni-ecosystem.png … 12-uni-activity-log.png
  docs/recordings/uni-demo-latest.webm (+ .mp4 when ffmpeg is available)

Usage:
  ALIEN_CAPTURE_BOOT=1 python3 scripts/capture_uni_media.py
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS = ROOT / "docs" / "screenshots"
RECORDINGS = ROOT / "docs" / "recordings"
BACKEND_PORT = int(os.environ.get("ALIEN_CAPTURE_BACKEND", "9110"))
FRONTEND_PORT = int(os.environ.get("ALIEN_CAPTURE_FRONTEND", "5174"))
BASE_URL = os.environ.get("ALIEN_CAPTURE_URL", f"http://127.0.0.1:{FRONTEND_PORT}").rstrip("/")
WAIT = int(os.environ.get("ALIEN_CAPTURE_WAIT_SEC", "8"))
VIDEO_WEBM = RECORDINGS / "uni-demo-latest.webm"
VIDEO_MP4 = RECORDINGS / "uni-demo-latest.mp4"
BOOT = os.environ.get("ALIEN_CAPTURE_BOOT", "1").strip().lower() in ("1", "true", "yes")

_procs: list[subprocess.Popen] = []


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _wait_stack(timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _http_ok(f"http://127.0.0.1:{BACKEND_PORT}/api/health") and _http_ok(BASE_URL):
            return
        time.sleep(1.5)
    raise RuntimeError(f"Stack not ready — backend :{BACKEND_PORT}, frontend {BASE_URL}")


def _boot_stack() -> None:
    python = str(_python_for_capture())

    env = os.environ.copy()
    env.update(
        {
            "ALIEN_MODE": "universe",
            "ALIEN_PORT": str(BACKEND_PORT),
            "HUB_URL": env.get("HUB_URL", "http://127.0.0.1:9083"),
            "AICOM_API_URL": env.get("AICOM_API_URL", "http://127.0.0.1:9081"),
            "PROMETHEUS_URL": env.get("PROMETHEUS_URL", "http://127.0.0.1:9090"),
            "MESH_URL": env.get("MESH_URL", "http://127.0.0.1:8090"),
        }
    )

    print(f"Starting UNI backend on :{BACKEND_PORT}...")
    _procs.append(
        subprocess.Popen(
            [python, "main.py"],
            cwd=str(ROOT / "backend"),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    )
    for _ in range(40):
        if _http_ok(f"http://127.0.0.1:{BACKEND_PORT}/api/health"):
            break
        time.sleep(1)
    else:
        raise RuntimeError("Backend failed to start")

    req = urllib.request.Request(
        f"http://127.0.0.1:{BACKEND_PORT}/api/universe/start",
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=120)

    fe = ROOT / "frontend"
    if not (fe / "node_modules").is_dir():
        subprocess.run(["npm", "install", "--silent"], cwd=str(fe), check=True)

    fe_env = {**env, "VITE_DEV_PROXY_PORT": str(BACKEND_PORT)}
    print(f"Starting frontend on :{FRONTEND_PORT}...")
    _procs.append(
        subprocess.Popen(
            ["npx", "vite", "--port", str(FRONTEND_PORT), "--host", "127.0.0.1"],
            cwd=str(fe),
            env=fe_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    )
    _wait_stack()


def _shutdown_stack() -> None:
    for proc in reversed(_procs):
        proc.send_signal(signal.SIGTERM)
    for proc in reversed(_procs):
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _chromium_args() -> list[str]:
    return [
        "--use-gl=swiftshader",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--enable-webgl",
        "--ignore-gpu-blocklist",
    ]


def _switch_uni(page) -> None:
    page.locator("button", has_text="UNI").first.click(timeout=10_000)
    page.wait_for_timeout(WAIT * 1000)


def _capture_screenshots(page) -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)

    print("[1/4] UNI ecosystem overview...")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(WAIT * 1000)
    _switch_uni(page)
    page.wait_for_timeout(WAIT * 1000)
    page.screenshot(path=str(SCREENSHOTS / "09-uni-ecosystem.png"))

    print("[2/4] UNI hub close-up...")
    page.locator("canvas").first.hover()
    for _ in range(8):
        page.mouse.wheel(0, -120)
        page.wait_for_timeout(80)
    page.wait_for_timeout(2000)
    page.screenshot(path=str(SCREENSHOTS / "10-uni-hub-closeup.png"))

    print("[3/4] UNI node inspector...")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(WAIT * 1000)
    _switch_uni(page)
    page.wait_for_timeout(WAIT * 1000)
    page.mouse.click(960, 460)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(SCREENSHOTS / "11-uni-node-detail.png"))

    print("[4/4] UNI activity log...")
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    page.screenshot(path=str(SCREENSHOTS / "12-uni-activity-log.png"))


def _record_video(page) -> None:
    print("Recording UNI demo video...")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(WAIT * 1000)
    _switch_uni(page)
    page.wait_for_timeout(WAIT * 1000)

    page.locator("canvas").first.hover()
    for i in range(14):
        page.mouse.move(900 + (i % 6) * 35, 450 + (i % 4) * 25)
        page.wait_for_timeout(180)
    for _ in range(7):
        page.mouse.wheel(0, -110)
        page.wait_for_timeout(320)
    page.wait_for_timeout(1200)
    page.mouse.click(960, 460)
    page.wait_for_timeout(2500)
    page.keyboard.press("Escape")
    page.wait_for_timeout(800)
    gr = page.locator("button", has_text="GR")
    if gr.count():
        gr.first.click()
        page.wait_for_timeout(1500)
    page.wait_for_timeout(2500)


def _python_for_capture() -> Path:
    venv_py = ROOT / "backend" / ".venv" / "bin" / "python3"
    if not venv_py.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / "backend" / ".venv")], check=True)
        subprocess.run(
            [str(ROOT / "backend" / ".venv" / "bin" / "pip"), "install", "-q", "-r", str(ROOT / "backend" / "requirements.txt")],
            check=True,
        )
    return venv_py


def _ensure_playwright():
    py = _python_for_capture()
    try:
        subprocess.run([str(py), "-c", "import playwright"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        subprocess.run([str(py), "-m", "pip", "install", "playwright", "-q"], check=True)
        subprocess.run([str(py), "-m", "playwright", "install", "chromium"], check=True)
    from playwright.sync_api import sync_playwright

    return sync_playwright


def main() -> int:
    sync_playwright = _ensure_playwright()
    RECORDINGS.mkdir(parents=True, exist_ok=True)

    if BOOT:
        _boot_stack()
    else:
        _wait_stack()

    video_src: Path | None = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=_chromium_args())
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
                record_video_dir=str(RECORDINGS),
                record_video_size={"width": 1920, "height": 1080},
            )
            page = context.new_page()
            _capture_screenshots(page)
            _record_video(page)
            video_src = page.video.path() if page.video else None
            context.close()
            browser.close()

        if video_src and Path(video_src).is_file():
            shutil.copy2(video_src, VIDEO_WEBM)
            print(f"  -> {VIDEO_WEBM}")
        if shutil.which("ffmpeg") and VIDEO_WEBM.is_file():
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(VIDEO_WEBM),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-pix_fmt", "yuv420p", str(VIDEO_MP4),
                ],
                check=False,
                capture_output=True,
            )
            if VIDEO_MP4.is_file():
                print(f"  -> {VIDEO_MP4}")
    finally:
        if BOOT:
            _shutdown_stack()

    print(f"\nDone — {len(list(SCREENSHOTS.glob('09-*.png')))} UNI screenshots, video in {RECORDINGS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
