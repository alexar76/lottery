#!/usr/bin/env python3
"""Capture Alien Monitor screenshots using Playwright (Python)."""

import os
import sys
import time
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = ROOT / "docs" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

BACKEND_PORT = 9100
FRONTEND_PORT = 5173
BASE_URL = f"http://localhost:{FRONTEND_PORT}"
WAIT = 6  # seconds to wait for WebGL + WebSocket + bloom to fully render


def main():
    from playwright.sync_api import sync_playwright

    print("=" * 60)
    print("  Alien Monitor — Screenshot Capture")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--use-gl=swiftshader',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--enable-webgl',
                '--ignore-gpu-blocklist',
            ],
        )
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            device_scale_factor=2,
        )
        page = context.new_page()

        # ── 1. Full ecosystem overview ────────────────────────────
        print("[1/8] Full ecosystem overview...")
        page.goto(BASE_URL, wait_until='domcontentloaded', timeout=30000)
        time.sleep(WAIT)
        page.screenshot(path=str(SCREENSHOTS_DIR / "01-full-ecosystem.png"))
        print(f"  -> 01-full-ecosystem.png")

        # ── 2. Zoom into center by scrolling ──────────────────────
        print("[2/8] Hub close-up...")
        canvas = page.locator('canvas')
        canvas.first.hover()
        for _ in range(10):
            page.mouse.wheel(0, -120)
            time.sleep(0.08)
        time.sleep(2)
        page.screenshot(path=str(SCREENSHOTS_DIR / "02-hub-closeup.png"))
        print(f"  -> 02-hub-closeup.png")

        # ── 3. Reload & click node for detail ─────────────────────
        print("[3/8] Node detail panel...")
        page.goto(BASE_URL, wait_until='domcontentloaded', timeout=15000)
        time.sleep(WAIT)
        # Click near center where hub should be
        page.mouse.click(960, 460)
        time.sleep(1.5)
        page.screenshot(path=str(SCREENSHOTS_DIR / "03-node-detail.png"))
        print(f"  -> 03-node-detail.png")

        # ── 4. AI Assistant open ──────────────────────────────────
        print("[4/8] AI Assistant panel...")
        page.keyboard.press('Escape')
        time.sleep(0.5)
        # Look for AI button
        ai_btn = page.locator('button', has_text='AI')
        if ai_btn.count() > 0:
            ai_btn.first.click()
            time.sleep(0.5)
        page.screenshot(path=str(SCREENSHOTS_DIR / "04-ai-assistant.png"))
        print(f"  -> 04-ai-assistant.png")

        # ── 5. AI answering question ──────────────────────────────
        print("[5/8] AI answering...")
        inp = page.locator('input[placeholder*="Ask"]')
        if inp.count() > 0:
            inp.first.fill("How do payment channels work?")
            time.sleep(0.3)
            page.keyboard.press('Enter')
            time.sleep(2)
        page.screenshot(path=str(SCREENSHOTS_DIR / "05-ai-answering.png"))
        print(f"  -> 05-ai-answering.png")

        # ── 6. Transaction flow ───────────────────────────────────
        print("[6/8] Transaction activity...")
        page.keyboard.press('Escape')
        time.sleep(0.3)
        page.screenshot(path=str(SCREENSHOTS_DIR / "06-transaction-flow.png"))
        print(f"  -> 06-transaction-flow.png")

        # ── 7. Magenta theme ──────────────────────────────────────
        print("[7/8] Magenta theme...")
        mg = page.locator('button', has_text='MG')
        if mg.count() > 0:
            mg.first.click()
            time.sleep(0.8)
        page.screenshot(path=str(SCREENSHOTS_DIR / "07-magenta-theme.png"))
        print(f"  -> 07-magenta-theme.png")

        # ── 8. Green theme, LIVE mode ─────────────────────────────
        print("[8/8] Green theme, LIVE...")
        gr = page.locator('button', has_text='GR')
        if gr.count() > 0:
            gr.first.click()
            time.sleep(0.3)
        live = page.locator('button', has_text='LIVE')
        if live.count() > 0:
            live.first.click()
            time.sleep(1)
        page.screenshot(path=str(SCREENSHOTS_DIR / "08-live-green.png"))
        print(f"  -> 08-live-green.png")

        browser.close()

    print(f"\nDone! {len(list(SCREENSHOTS_DIR.glob('*.png')))} screenshots in {SCREENSHOTS_DIR}")


if __name__ == "__main__":
    main()
