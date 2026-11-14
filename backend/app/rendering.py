"""Bounded local script-to-scenes renderer. No external assets or speech synthesis."""

import hashlib
import json
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_seconds: int = Field(ge=0, le=59, strict=True)
    duration_seconds: int = Field(ge=1, le=15, strict=True)
    text: str = Field(min_length=1, max_length=160)

    @field_validator("text")
    @classmethod
    def clean_text(cls, text):
        if any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise ValueError("Control characters not supported")
        normalized = " ".join(text.split())
        if not normalized:
            raise ValueError("Empty scene")
        return normalized


class Storyboard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: list[Scene] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def timing(self):
        position = 0
        for scene in self.scenes:
            if scene.start_seconds != position:
                raise ValueError("Scenes must be contiguous from zero")
            position += scene.duration_seconds
        if position > 60:
            raise ValueError("Maximum video duration is 60 seconds")
        return self

    @classmethod
    def from_concept(cls, concept):
        words = textwrap.wrap(concept["script"], width=140, break_long_words=True)
        texts = [concept["hook"][:160], *words][:8]
        return cls(
            scenes=[
                Scene(start_seconds=i * 4, duration_seconds=4, text=t) for i, t in enumerate(texts)
            ]
        )


def validate_video(path, expected=None):
    response = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=15,
    )
    info = json.loads(response.stdout)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    duration = float(info["format"]["duration"])
    if (
        "mp4" not in info["format"]["format_name"]
        or stream["width"] != 540
        or stream["height"] != 960
        or duration > 60.2
        or duration < 1
        or (expected is not None and abs(duration - expected) > 0.2)
    ):
        raise ValueError("Invalid video dimensions, container or duration")
    return {"width": 540, "height": 960, "duration_seconds": duration, "container": "mp4"}


class LocalRenderer:
    def render(self, job_id, destination, *, storyboard=None):
        if not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", job_id):
            raise ValueError("Invalid artifact identifier")
        storyboard = storyboard or Storyboard(
            scenes=[
                Scene(start_seconds=0, duration_seconds=4, text="Local script video"),
                Scene(
                    start_seconds=4,
                    duration_seconds=4,
                    text="Text-based production without voiceover",
                ),
            ]
        )
        storyboard = Storyboard.model_validate(storyboard)
        if destination.suffix != ".mp4" or not FONT.is_file():
            raise ValueError("MP4 destination and local DejaVu font required")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="lc_render_") as temporary:
            root = Path(temporary)
            clips = []
            for i, scene in enumerate(storyboard.scenes):
                text = root / f"text{i}.txt"
                text.write_text("\n".join(textwrap.wrap(scene.text, width=16)), encoding="utf-8")
                output = root / f"scene{i}.mp4"
                color = ["0x183d35", "0x243450", "0x40314e"][i % 3]
                filters = (
                    f"drawtext=fontfile={FONT}:textfile={text}:expansion=none:"
                    "fontcolor=white:fontsize=30:line_spacing=14:x=(w-tw)/2:y=(h-th)/2"
                )
                subprocess.run(
                    [
                        "ffmpeg",
                        "-nostdin",
                        "-y",
                        "-v",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        f"color=c={color}:s=540x960:r=12:d={scene.duration_seconds}",
                        "-vf",
                        filters,
                        "-c:v",
                        "libx264",
                        "-threads",
                        "1",
                        "-pix_fmt",
                        "yuv420p",
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=35,
                )
                clips.append(output)
            manifest = root / "clips.txt"
            manifest.write_text("".join(f"file '{p.name}'\n" for p in clips))
            final = root / "video.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-y",
                    "-v",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "1",
                    "-i",
                    str(manifest),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(final),
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            info = validate_video(final, sum(s.duration_seconds for s in storyboard.scenes))
            content = final.read_bytes()
            if destination.is_file():
                previous = destination.read_bytes()
                (destination.parent / f"{hashlib.sha256(previous).hexdigest()}.mp4").write_bytes(
                    previous
                )
            staged = destination.with_suffix(".staged.mp4")
            staged.write_bytes(content)
            staged.replace(destination)
        return {
            **info,
            "simulation": False,
            "production_kind": "local_script_text",
            "sha256": hashlib.sha256(content).hexdigest(),
            "storyboard": storyboard.model_dump(),
            "voiceover": False,
            "external_imagery": False,
            "format": "9:16",
            "assets": {
                "background": "locally generated colors",
                "font": "DejaVu Sans — Bitstream Vera/DejaVu license",
            },
            "description": "Real script-dependent local text video; no voiceover or external imagery",
        }
