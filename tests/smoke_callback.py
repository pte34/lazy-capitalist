"""Browser check of local owner cookie/CSRF and disabled OAuth. No Google requests."""

import os

from playwright.sync_api import sync_playwright

token = os.environ["SMOKE_API_TOKEN"]
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("http://127.0.0.1:8000/health")
    result = page.evaluate(
        """async token => {
      const login=await fetch('/owner/session',{method:'POST',headers:{Authorization:'Bearer '+token}});
      const start=await fetch('/oauth/youtube/start',{method:'POST'});
      return {login:login.status,start:start.status,cookies:document.cookie};
    }""",
        token,
    )
    assert result == {"login": 200, "start": 503, "cookies": ""}
    cookies = page.context.cookies()
    assert any(
        c["name"] == "lc_owner" and c["httpOnly"] and c["sameSite"] == "Lax"
        for c in cookies
    )
    response = page.goto(
        "http://127.0.0.1:8000/oauth/youtube/callback?state=test&code=not-a-real-code"
    )
    assert response.status == 503
    assert "not-a-real-code" not in page.locator("body").inner_text()
    assert page.evaluate("localStorage.length") == 0
    browser.close()
    print(
        "PASS: owner bootstrap, HttpOnly cookie, disabled OAuth start/callback, no browser token storage"
    )
