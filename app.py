from __future__ import annotations

import asyncio
import os
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
SPOTDL = ROOT / ".venv" / "bin" / "spotdl"
FFMPEG = ROOT / ".config" / "spotdl" / "ffmpeg"
COOKIE_FILE = ROOT / ".cache" / "youtube-cookies.txt"
DOWNLOADS = ROOT / "downloads"
STATIC = ROOT / "static"

ALLOWED_FORMATS = {"mp3", "flac", "ogg", "opus", "m4a", "wav"}
ALLOWED_BITRATES = {
    "auto",
    "disable",
    "128k",
    "160k",
    "192k",
    "256k",
    "320k",
}
MEDIA_EXTENSIONS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav"}

DOWNLOADS.mkdir(exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DownloadJob:
    id: str
    query: str
    status: str = "queued"
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    log: Deque[str] = field(default_factory=lambda: deque(maxlen=500))

    def public(self) -> dict:
        return {
            "id": self.id,
            "query": self.query,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "return_code": self.return_code,
            "log": list(self.log),
        }


class DownloadRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    format: str = "mp3"
    bitrate: str = "128k"
    overwrite: str = "skip"


jobs: dict[str, DownloadJob] = {}

app = FastAPI(title="SpotDL Web Downloader")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": SPOTDL.exists(),
        "spotdl": str(SPOTDL),
        "downloads": str(DOWNLOADS),
    }


@app.post("/api/downloads")
async def start_download(request: DownloadRequest) -> dict:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Enter a Spotify song, album, or playlist URL.")
    if request.format not in ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail="Unsupported audio format.")
    if request.bitrate not in ALLOWED_BITRATES:
        raise HTTPException(status_code=400, detail="Unsupported bitrate.")
    if request.overwrite not in {"skip", "force", "metadata"}:
        raise HTTPException(status_code=400, detail="Unsupported overwrite mode.")
    if not SPOTDL.exists():
        raise HTTPException(status_code=500, detail="spotdl is not installed in .venv/bin/spotdl.")

    job = DownloadJob(id=uuid.uuid4().hex[:12], query=query)
    jobs[job.id] = job
    asyncio.create_task(run_spotdl(job, request))
    return job.public()


@app.get("/api/downloads/{job_id}")
def get_download(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Download job not found.")
    return job.public()


@app.get("/api/files")
def list_files() -> dict:
    files = []
    for path in sorted(DOWNLOADS.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "url": f"/api/files/{path.name}",
            }
        )
    return {"files": files}


@app.get("/api/files/{filename}")
def get_file(filename: str) -> FileResponse:
    path = (DOWNLOADS / filename).resolve()
    if DOWNLOADS.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    if path.suffix.lower() not in MEDIA_EXTENSIONS:
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, filename=path.name)


async def run_spotdl(job: DownloadJob, request: DownloadRequest) -> None:
    job.status = "running"
    job.started_at = now_iso()

    output_template = str(DOWNLOADS / "{artists} - {title}.{output-ext}")
    command = [
        str(SPOTDL),
        "download",
        job.query,
        "--config",
        "--output",
        output_template,
        "--format",
        request.format,
        "--bitrate",
        request.bitrate,
        "--overwrite",
        request.overwrite,
        "--restrict",
        "ascii",
        "--print-errors",
        "--log-level",
        "INFO",
    ]
    if FFMPEG.exists():
        command.extend(["--ffmpeg", str(FFMPEG)])
    if COOKIE_FILE.exists():
        command.extend(["--cookie-file", str(COOKIE_FILE)])

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(ROOT),
            "XDG_CONFIG_HOME": str(ROOT / ".config"),
            "XDG_CACHE_HOME": str(ROOT / ".cache"),
            "PYTHONUNBUFFERED": "1",
        }
    )

    job.log.append("Starting spotdl...")
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    assert process.stdout is not None
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        job.log.append(line.decode(errors="replace").rstrip())

    job.return_code = await process.wait()
    job.finished_at = now_iso()
    job.status = "complete" if job.return_code == 0 else "failed"
    if job.status == "complete":
        job.log.append("Download finished.")
    else:
        job.log.append(f"spotdl exited with code {job.return_code}.")
