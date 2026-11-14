"""Durable local MVP steps. No network rendering or publishing is enabled."""

import json
import time
from pathlib import Path
from typing import Literal, Protocol

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.rendering import LocalRenderer, Storyboard
from app.store import Store
from app.youtube import Metadata, fingerprint

STEPS = ("quality", "media", "render", "preview", "approval", "upload")


class Renderer(Protocol):
    def render(self, job_id: str, destination: Path, *, storyboard: Storyboard) -> dict: ...


class Publisher(Protocol):
    def upload(
        self,
        job_id: str,
        video: Path,
        privacy: Literal["private"],
        *,
        metadata: dict,
        approval: str,
    ) -> dict: ...


class SimulatedYouTube:
    def upload(self, job_id, video, privacy, *, metadata=None, approval=None):
        if privacy != "private":
            raise ValueError("Public publishing disabled")
        return {
            "simulation": True,
            "privacy": "private",
            "receipt": f"simulated:{job_id}",
            "youtube_video_id": None,
            "url": None,
        }


class Approval(BaseModel):
    approved: bool
    privacy: Literal["private"] = "private"
    made_for_kids: bool = False
    synthetic_media: bool = True


class CostReconciliation(BaseModel):
    actual_usd: float = Field(ge=0, allow_inf_nan=False)
    billing_reference: str = Field(min_length=3, max_length=200)


class Pause(BaseModel):
    paused: bool


class Workflow:
    def __init__(
        self, store: Store, renderer: Renderer | None = None, publisher: Publisher | None = None
    ):
        self.store = store
        self.renderer = renderer or LocalRenderer()
        self.publisher = publisher or SimulatedYouTube()
        self.assets = Path(store.path).parent / "videos"

    def snapshot(self, job_id):
        job = self.store.job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        with self.store.connect() as db:
            for name in STEPS:
                db.execute(
                    "INSERT OR IGNORE INTO workflow_steps(job_id,name) VALUES(?,?)", (job_id, name)
                )
            rows = db.execute("SELECT * FROM workflow_steps WHERE job_id=?", (job_id,)).fetchall()
            paused = bool(db.execute("SELECT paused FROM system_state WHERE id=1").fetchone()[0])
        with self.store.connect() as db:
            metadata = db.execute(
                "SELECT model,prompt_version FROM job_metadata WHERE job_id=?", (job_id,)
            ).fetchone()
        by_name = {row["name"]: dict(row) for row in rows}
        for row in by_name.values():
            row["result"] = json.loads(row["result"]) if row["result"] else None
        return {
            "job": job,
            "steps": [by_name[name] for name in STEPS],
            "paused": paused,
            "simulation": True,
            "performance": None,
            "revenue": None,
            "metadata": {
                "model": metadata["model"] if metadata else "unknown",
                "prompt_version": "concept-v1",
                "baseline": "concept-v1",
                "format": "9:16",
                "hook": (job["result"] or {}).get("hook"),
                "script_duration_seconds": (job["result"] or {}).get("duration_seconds"),
            },
        }

    def run(self, job_id):
        snapshot = self.snapshot(job_id)
        if snapshot["job"]["status"] != "succeeded":
            raise HTTPException(
                409, "Script must succeed first; ambiguous paid calls need reconciliation"
            )
        for step in snapshot["steps"]:
            name = step["name"]
            if name == "approval" and step["status"] != "succeeded":
                break
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT paused FROM system_state WHERE id=1").fetchone()[0]:
                    raise HTTPException(423, "System paused")
                current = db.execute(
                    "SELECT * FROM workflow_steps WHERE job_id=? AND name=?", (job_id, name)
                ).fetchone()
                if current["status"] == "succeeded":
                    continue
                if current["status"] == "running":
                    raise HTTPException(409, "Step outcome uncertain; reconcile before retry")
                if current["attempts"] >= 3 or current["next_retry"] > time.time():
                    raise HTTPException(409, "Retry limit reached or backoff active")
                db.execute(
                    "UPDATE workflow_steps SET status='running', attempts=attempts+1, updated=? "
                    "WHERE job_id=? AND name=?",
                    (time.time(), job_id, name),
                )
            try:
                result = self.execute(job_id, name, snapshot["job"])
            except Exception:
                with self.store.connect() as db:
                    db.execute(
                        "UPDATE workflow_steps SET status='failed',error=?,next_retry=? "
                        "WHERE job_id=? AND name=?",
                        (
                            "Local step failed; verify FFmpeg and quality report",
                            time.time() + 2 ** (current["attempts"] + 1),
                            job_id,
                            name,
                        ),
                    )
                    db.execute(
                        "INSERT INTO audit_events(job_id,action) VALUES(?,?)",
                        (job_id, f"{name}_failed"),
                    )
                raise HTTPException(502, f"{name} failed; retry after backoff") from None
            with self.store.connect() as db:
                db.execute(
                    "UPDATE workflow_steps SET status='succeeded',result=?,error=NULL "
                    "WHERE job_id=? AND name=?",
                    (json.dumps(result), job_id, name),
                )
                db.execute(
                    "INSERT INTO audit_events(job_id,action) VALUES(?,?)",
                    (
                        job_id,
                        f"{name}_succeeded" + (":simulated" if result.get("simulation") else ""),
                    ),
                )
        return self.snapshot(job_id)

    def upload_metadata(self, job, flags):
        return {
            "title": job["result"]["title"][:100],
            "description": job["result"]["script"],
            "privacy": "private",
            "made_for_kids": flags["made_for_kids"],
            "synthetic_media": flags["synthetic_media"],
        }

    def execute(self, job_id, name, job):
        concept = job["result"]
        if name == "quality":
            sentences = [s.strip().lower() for s in concept["script"].split(".") if s.strip()]
            repeated = len(sentences) != len(set(sentences))
            # Heuristics are advisory; never claim automated factual verification.
            return {
                "repeated_sentences": repeated,
                "fact_check": "unknown",
                "original_value": "owner_review_required",
                "requires_owner_review": True,
                "claims": "No source verification available",
                "hook": concept["hook"],
            }
        if name == "media":
            return {
                "simulation": False,
                "source": "locally generated scene backgrounds and installed DejaVu Sans font",
                "rights": "Generated synthetic background; no third-party media",
                "license": "No external media license required",
                "attribution": None,
            }
        video = self.assets / f"{job_id}.mp4"
        if name == "render":
            with self.store.connect() as db:
                custom = db.execute(
                    "SELECT script FROM storyboards WHERE job_id=?", (job_id,)
                ).fetchone()
            board = (
                Storyboard.model_validate_json(custom[0])
                if custom
                else Storyboard.from_concept(concept)
            )
            return self.renderer.render(job_id, video, storyboard=board)
        if name == "preview":
            if not video.is_file():
                raise ValueError("Missing preview")
            return {
                "preview": f"/jobs/{job_id}/video",
                "simulation": False,
                "production_kind": "local_script_text",
            }
        if name == "upload":
            with self.store.connect() as db:
                approved = json.loads(
                    db.execute(
                        "SELECT result FROM workflow_steps WHERE job_id=? AND name='approval'",
                        (job_id,),
                    ).fetchone()[0]
                )
            metadata = self.upload_metadata(job, approved)
            if approved.get("artifact") != fingerprint(
                video, Metadata.model_validate(metadata).payload()
            ):
                with self.store.connect() as db:
                    db.execute(
                        "UPDATE workflow_steps SET status='pending' WHERE job_id=? AND name='approval'",
                        (job_id,),
                    )
                raise ValueError("Approval invalidated by artifact or metadata change")
            return self.publisher.upload(
                job_id, video, "private", metadata=metadata, approval=approved["artifact"]
            )
        raise ValueError("Unsupported step")


def register_routes(app, workflow, authorize):
    protected = [Depends(authorize)]

    @app.put("/jobs/{job_id}/storyboard", dependencies=protected)
    def set_storyboard(job_id: str, body: Storyboard):
        workflow.snapshot(job_id)
        with workflow.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT name,status FROM workflow_steps WHERE job_id=?", (job_id,)
            ).fetchall()
            if any(
                r["status"] == "running" or (r["name"] == "upload" and r["status"] != "pending")
                for r in rows
            ):
                raise HTTPException(409, "Active or attempted upload prevents artifact editing")
            db.execute(
                "INSERT OR REPLACE INTO storyboards VALUES(?,?)", (job_id, body.model_dump_json())
            )
            db.execute(
                "UPDATE workflow_steps SET status='pending',attempts=0,result=NULL,error=NULL,next_retry=0 WHERE job_id=? AND name IN ('render','preview','approval')",
                (job_id,),
            )
            db.execute(
                "INSERT INTO audit_events(job_id,action) VALUES(?,?)",
                (job_id, "storyboard_updated_approval_invalidated"),
            )
        return workflow.snapshot(job_id)

    @app.post("/jobs/{job_id}/cost-reconciliation", dependencies=protected)
    def cost_reconciliation(job_id: str, body: CostReconciliation):
        job = workflow.store.job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job["status"] == "running" or job["provider"] == "mock":
            raise HTTPException(409, "Cannot reconcile running or mock usage")
        with workflow.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE ai_usage SET cost_usd=?,cost_kind='actual' WHERE job_id=?",
                (body.actual_usd, job_id),
            )
            db.execute(
                "INSERT INTO audit_events(job_id,action) VALUES(?,?)",
                (job_id, "owner_billing_reconciled:" + body.billing_reference),
            )
        return {
            "actual_usd": body.actual_usd,
            "source": "owner_supplied_billing",
            "verified_by_provider": False,
        }

    @app.get("/system", dependencies=protected)
    def system():
        with workflow.store.connect() as db:
            return {
                "paused": bool(
                    db.execute("SELECT paused FROM system_state WHERE id=1").fetchone()[0]
                )
            }

    @app.post("/system/pause", dependencies=protected)
    def pause(body: Pause):
        with workflow.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE system_state SET paused=? WHERE id=1", (body.paused,))
            db.execute(
                "INSERT INTO audit_events(action) VALUES(?)",
                ("paused" if body.paused else "resumed",),
            )
        return {"paused": body.paused}

    @app.get("/jobs/{job_id}/workflow", dependencies=protected)
    def state(job_id: str):
        return workflow.snapshot(job_id)

    @app.post("/jobs/{job_id}/run", dependencies=protected)
    def run(job_id: str):
        return workflow.run(job_id)

    @app.post("/jobs/{job_id}/approval", dependencies=protected)
    def approve(job_id: str, body: Approval):
        state = workflow.snapshot(job_id)
        if any(s["status"] != "succeeded" for s in state["steps"][:4]):
            raise HTTPException(409, "Preview and quality checks required")
        with workflow.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT status FROM workflow_steps WHERE job_id=? AND name='upload'", (job_id,)
                ).fetchone()[0]
                != "pending"
            ):
                raise HTTPException(409, "Upload already started")
            db.execute(
                "UPDATE workflow_steps SET status=?,result=? WHERE job_id=? AND name='approval'",
                (
                    "succeeded" if body.approved else "pending",
                    json.dumps(
                        {
                            "owner_reviewed": body.approved,
                            "privacy": "private",
                            "made_for_kids": body.made_for_kids,
                            "synthetic_media": body.synthetic_media,
                            "artifact": fingerprint(
                                workflow.assets / f"{job_id}.mp4",
                                Metadata.model_validate(
                                    workflow.upload_metadata(state["job"], body.model_dump())
                                ).payload(),
                            ),
                        }
                    ),
                    job_id,
                ),
            )
            db.execute(
                "INSERT INTO audit_events(job_id,action) VALUES(?,?)",
                (
                    job_id,
                    "approved_private:simulated" if body.approved else "approval_revoked:simulated",
                ),
            )
        return workflow.snapshot(job_id)

    @app.post("/jobs/{job_id}/reconcile", dependencies=protected)
    def reconcile(job_id: str):
        workflow.snapshot(job_id)
        # Only deterministic local/simulated operations may be reset. No real upload adapter exists.
        with workflow.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute(
                "SELECT * FROM workflow_steps WHERE job_id=? AND status='running'", (job_id,)
            ).fetchall()
            if any(time.time() - row["updated"] < 120 for row in active):
                raise HTTPException(409, "Step may still be active")
            db.execute(
                "UPDATE workflow_steps SET status='failed',error='Interrupted local operation' "
                "WHERE job_id=? AND status='running'",
                (job_id,),
            )
            db.execute(
                "INSERT INTO audit_events(job_id,action) VALUES(?,?)", (job_id, "local_reconciled")
            )
        return workflow.snapshot(job_id)

    @app.get("/jobs/{job_id}/video", dependencies=protected)
    def video(job_id: str):
        state = workflow.snapshot(job_id)
        if state["steps"][2]["status"] != "succeeded":
            raise HTTPException(404, "Preview not ready")
        path = workflow.assets / f"{state['job']['id']}.mp4"
        if not path.is_file():
            raise HTTPException(404, "Preview artifact missing")
        return FileResponse(path, media_type="video/mp4")
