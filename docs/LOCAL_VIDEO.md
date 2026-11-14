# Local script video

`LocalRenderer` now renders real script-dependent text scenes, not a placeholder slate. MP4: 540×960, 12 fps, H.264/yuv420p, 2–8 scenes, contiguous integer times, 1–15 seconds per scene, total at most 60 seconds. Text is limited to 160 characters per scene and wrapped to 16 characters per line at 30 px. No narration, speech synthesis, photographs or externally sourced media are included. Generated colors are local; font is system DejaVu Sans (`/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`), distributed under the Bitstream Vera/DejaVu license; system package copyright is at `/usr/share/doc/fonts-dejavu-core/copyright`. No font binary is vendored.

Use `examples/storyboard.json` or `PUT /jobs/{id}/storyboard` with the existing bearer protection. The workflow otherwise derives scenes from the saved hook/script. Editing a storyboard resets rendering, preview and approval, while retaining completed earlier steps. Jobs with active steps or attempted upload cannot be edited. Replaced MP4 files are preserved under their content hash. Existing hash-bound approval rejects changes independently.

Local example from repository root:

```
PYTHONPATH=backend uv run --project backend python -c "from app.rendering import LocalRenderer,Storyboard; from pathlib import Path; LocalRenderer().render('example',Path('work/script-video.mp4'),storyboard=Storyboard.model_validate_json(Path('examples/storyboard.json').read_text()))"
```

Requires FFmpeg, ffprobe, libx264, drawtext and the DejaVu font. User text goes into bounded text files with drawtext expansion disabled, never into a shell or filter expression. Rendering uses argv lists, a private temporary directory, fixed resolution/fps, one encoder thread and subprocess timeouts. ffprobe checks output container, video dimensions and duration. Temporary files are removed on failure. Local scene extraction is deterministic and does not establish factual accuracy or original value.

Verification: rendering tests compare hashes after script changes, reject invalid timing/broken files, check ffprobe output and invalidate approvals on updates. `tests/smoke_local_preview.py` exercises UI through preview without upload. Example frame was visually inspected: text readable, centered and within image bounds. Google remains untouched; local rendering is genuine, publishing remains simulated.
