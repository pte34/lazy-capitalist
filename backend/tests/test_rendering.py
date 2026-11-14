import subprocess

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.rendering import LocalRenderer, Storyboard, validate_video

BOARD = {
    "scenes": [
        {"start_seconds": 0, "duration_seconds": 2, "text": "Start with one small experiment."},
        {
            "start_seconds": 2,
            "duration_seconds": 2,
            "text": "Measure the result. Learn and repeat.",
        },
    ]
}


def test_real_render_changes_content_and_validates(tmp_path):
    renderer = LocalRenderer()
    board = Storyboard.model_validate(BOARD)
    first = renderer.render("test", tmp_path / "video.mp4", storyboard=board)
    assert first["simulation"] is False
    assert validate_video(tmp_path / "video.mp4", 4)["width"] == 540
    board.scenes[1].text = "A different script produces a different scene."
    second = renderer.render("test", tmp_path / "video.mp4", storyboard=board)
    assert first["sha256"] != second["sha256"]
    (tmp_path / "broken.mp4").write_bytes(b"broken")
    with pytest.raises(subprocess.CalledProcessError):
        validate_video(tmp_path / "broken.mp4")


@pytest.mark.parametrize(
    "change",
    [{"start_seconds": 1}, {"duration_seconds": 0}, {"duration_seconds": 16}, {"text": "x" * 161}],
)
def test_invalid_storyboards(change):
    board = {**BOARD, "scenes": [{**BOARD["scenes"][0], **change}, BOARD["scenes"][1]]}
    with pytest.raises(ValidationError):
        Storyboard.model_validate(board)


def test_storyboard_update_invalidates_approval(tmp_path):
    client = TestClient(create_app(Settings(database_path=str(tmp_path / "db"), _env_file=None)))
    job = client.post("/jobs", json={"topic": "Local video"}).json()["id"]
    assert client.put(f"/jobs/{job}/storyboard", json=BOARD).status_code == 200
    assert client.post(f"/jobs/{job}/run").status_code == 200
    client.post(f"/jobs/{job}/approval", json={"approved": True})
    result = client.put(f"/jobs/{job}/storyboard", json=BOARD).json()
    assert result["steps"][2]["status"] == "pending"
    assert result["steps"][4]["status"] == "pending"
