"""Optional browser smoke test; start backend, dev :3000 and built frontend :3001 first."""

from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    Path("work").mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.goto("http://127.0.0.1:3000")
        page.get_by_label("What should your next video explore?").fill(
            "Small habits for better learning"
        )
        page.get_by_role("button", name="Generate concept").click()
        page.get_by_role("status").filter(
            has_text="Concept saved to the backend."
        ).wait_for()
        assert page.get_by_text(
            "A quick guide to Small habits for better learning", exact=True
        ).is_visible()
        for section in [
            "Content Pipeline",
            "Agent Status",
            "Financial Overview",
            "System Health",
            "Overview",
        ]:
            page.get_by_role("button", name=section, exact=True).click()
            assert page.get_by_role("heading", name=section, exact=True).is_visible()
        page.screenshot(path="work/dashboard-desktop.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.screenshot(path="work/dashboard-mobile.png", full_page=True)
        response = page.request.post(
            "http://127.0.0.1:3001/api/jobs", data={"topic": "Should be blocked"}
        )
        assert response.status == 403
        browser.close()
    print("PASS: generation, navigation, mobile layout, hosted writes blocked")


if __name__ == "__main__":
    main()
