from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright

Path("work").mkdir(exist_ok=True)
topic = f"Browser MVP {uuid4().hex[:8]}"
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.goto("http://127.0.0.1:3000")
    page.get_by_label("What should your next video explore?").fill(topic)
    page.get_by_role("button", name="Generate concept").click()
    page.get_by_text("Concept saved to the backend.", exact=True).wait_for()
    page.get_by_role("button", name="Warteschlange aktualisieren").click()
    page.locator("#queue option").filter(has_text=topic).wait_for(state="attached")
    page.locator("#queue").select_option(label=topic)
    page.get_by_role("button", name="Ausführen / fortsetzen").click()
    page.get_by_label("Simulierte Video-Vorschau").wait_for()
    page.on("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Nach Prüfung privat freigeben").click()
    page.get_by_text("approval: succeeded", exact=False).wait_for()
    page.get_by_role("button", name="Ausführen / fortsetzen").click()
    page.get_by_text("upload: succeeded", exact=False).wait_for()
    page.get_by_role("button", name="Global pausieren").click()
    page.get_by_role("button", name="Fortsetzen", exact=True).wait_for()
    assert page.get_by_role("button", name="Ausführen / fortsetzen").is_disabled()
    page.get_by_role("button", name="Fortsetzen", exact=True).click()
    page.screenshot(path="work/mvp-browser.png", full_page=True)
    b.close()
    print(
        "PASS: UI queue, MP4 preview, approval, simulated private upload and global pause"
    )
