"""Run with local backend and Next dev server; no Google navigation or upload."""

from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright

Path("work").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    page.goto("http://127.0.0.1:3000")
    topic = "Script preview " + uuid4().hex[:8]
    page.get_by_label("What should your next video explore?").fill(topic)
    page.get_by_role("button", name="Generate concept").click()
    page.get_by_text("Concept saved to the backend.", exact=True).wait_for()
    page.get_by_role("button", name="Warteschlange aktualisieren").click()
    page.locator("#queue option").filter(has_text=topic).wait_for(state="attached")
    page.locator("#queue").select_option(label=topic)
    page.get_by_role("button", name="Ausführen / fortsetzen").click()
    video = page.get_by_label("Lokale skriptbasierte Video-Vorschau")
    video.wait_for()
    page.wait_for_function('document.querySelector("video")?.videoWidth === 540')
    assert page.get_by_text("approval: pending", exact=False).is_visible()
    assert page.get_by_text("upload: pending", exact=False).is_visible()
    page.screenshot(path="work/local-preview-browser.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert (
        page.request.get(
            "http://127.0.0.1:8000/oauth/youtube/callback?state=test&code=test"
        ).status
        == 401
    )
    browser.close()
    print(
        "PASS: script MP4 preview, dimensions, pending upload, mobile layout, protected callback"
    )
