"""Create five real local videos and a synthetic channel warning; never publish."""

import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

root = Path("work/command-smoke")
root.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    requests = []
    page.on("request", lambda r: requests.append(r.url))
    page.goto("http://127.0.0.1:3000")
    with page.expect_response(
        lambda r: "/commands" in unquote(r.url) and r.request.method == "POST"
    ) as response:
        page.get_by_role("button", name="Auftrag planen", exact=True).click()
    order = response.value.json()
    assert order["plan"]["count"] == 5 and order["plan"]["budget_chf"] == "3"
    page.get_by_label("Editierbarer Plan", exact=False).wait_for()
    plan = order["plan"]
    plan["references"] = ["https://example.test/inspiration-only"]
    page.locator("#command-plan").fill(json.dumps(plan, ensure_ascii=False))
    with page.expect_response(
        lambda r: "/commands/" in unquote(r.url) and unquote(r.url).endswith("/plan")
    ):
        page.get_by_role("button", name="Plan speichern", exact=True).click()
    with page.expect_response(
        lambda r: "/commands/" in unquote(r.url) and unquote(r.url).endswith("/approve")
    ):
        page.get_by_role("button", name="Nur lokale Produktion freigeben").click()
    with page.expect_response(
        lambda r: "/commands/" in unquote(r.url) and unquote(r.url).endswith("/run"),
        timeout=120000,
    ) as response:
        page.get_by_role("button", name="Lokal produzieren / fortsetzen").click()
    order = response.value.json()
    assert order["status"] == "previews_ready" and len(order["videos"]) == 5
    hashes = []
    for video in order["videos"]:
        assert video["workflow"]["steps"][-1]["status"] == "pending"
        response = page.request.get(
            "http://127.0.0.1:3000/api/jobs?path="
            + f"%2Fjobs%2F{video['job_id']}%2Fvideo"
        )
        assert response.status == 200
        file = root / f"video-{video['number']}.mp4"
        file.write_bytes(response.body())
        hashes.append(hashlib.sha256(file.read_bytes()).hexdigest())
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=width,height:format=duration",
                "-of",
                "json",
                str(file),
            ],
            check=True,
            capture_output=True,
        )
        info = json.loads(probe.stdout)
        assert (
            info["streams"][0]["width"] == 540 and info["streams"][0]["height"] == 960
        )
        assert abs(float(info["format"]["duration"]) - 20) < 0.2
    assert len(set(hashes)) == 5
    first = page.get_by_label("Auftragsvideo 1", exact=True)
    first.scroll_into_view_if_needed()
    first.screenshot(path=str(root / "preview-browser.png"))
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            "2",
            "-i",
            str(root / "video-1.mp4"),
            "-frames:v",
            "1",
            str(root / "representative-frame.png"),
        ],
        check=True,
    )
    channel = "smoke-" + order["id"][:8]
    page.locator("#signal-channel").fill(channel)
    page.locator("#signal-source").select_option("mock_platform_signal")
    page.locator("#signal-note").fill(
        "Synthetic browser test; no actual platform strike."
    )
    with page.expect_response(lambda r: "/platforms/events" in unquote(r.url)):
        page.get_by_role("button", name="Meldung lokal speichern", exact=True).click()
    page.get_by_role("alert").filter(has_text="Kritisch:").wait_for()
    page.on(
        "dialog",
        lambda d: d.accept(
            "Owner-reviewed synthetic browser test only; clear test channel."
        ),
    )
    article = page.locator("article").filter(has_text=channel)
    with page.expect_response(lambda r: "/platforms/review" in unquote(r.url)):
        article.get_by_role("button", name="Nach Owner-Prüfung entsperren").click()
    page.get_by_role("button", name="Berichte laden", exact=True).click()
    page.get_by_text("Berichte aktualisiert.", exact=True).wait_for()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert all(
        url.startswith(("http://127.0.0.1:3000", "ws://127.0.0.1:3000"))
        for url in requests
    )
    (root / "result.json").write_text(
        json.dumps(
            {
                "order_id": order["id"],
                "videos": [v["job_id"] for v in order["videos"]],
                "sha256": hashes,
                "simulation": "research and publishing only; local videos real",
            },
            indent=2,
        )
    )
    browser.close()
    print(
        "PASS: five unique 540x960/20s local MP4s, plan/production approvals, no upload, channel warning/review, reports and mobile UI"
    )
