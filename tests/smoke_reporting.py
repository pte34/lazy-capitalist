"""Local UI smoke with server-only BACKEND_API_TOKEN; no real delivery or Google login."""

from pathlib import Path

from playwright.sync_api import sync_playwright

Path("work").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    page.goto("http://127.0.0.1:3000")
    page.get_by_role("button", name="Berichte laden", exact=True).click()
    page.get_by_text("Berichte aktualisiert.", exact=True).wait_for()
    page.get_by_label("E-Mail für Mock-Tests", exact=True).fill("owner@example.test")
    page.get_by_label("WhatsApp für Mock-Tests (E.164)", exact=True).fill(
        "+41790000000"
    )
    page.get_by_role("button", name="Mock-Einstellungen speichern").click()
    page.get_by_text("Berichte aktualisiert.", exact=True).wait_for()
    page.get_by_role("button", name="Fällige Berichte verarbeiten").click()
    page.get_by_text("Berichte aktualisiert.", exact=True).wait_for()
    page.get_by_role("button", name="Simulierte Testzustellung", exact=True).click()
    page.get_by_text(
        "Mock-Zustellung verarbeitet. Keine echte Nachricht gesendet.", exact=True
    ).wait_for()
    assert page.get_by_text("email: simulated", exact=False).first.is_visible()
    assert page.get_by_text("whatsapp: simulated", exact=False).first.is_visible()
    page.get_by_text("Gespeicherte Berichte", exact=True).scroll_into_view_if_needed()
    page.screenshot(path="work/reporting-browser.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    browser.close()
    print(
        "PASS: reports, recipient validation/settings, bundled mock notifications, history, mobile layout"
    )
