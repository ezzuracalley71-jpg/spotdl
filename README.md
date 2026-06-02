# SpotDL Web Tool

A local FastAPI page for downloading Spotify tracks, albums, and playlists with the `spotdl` virtualenv in this workspace.

## Run

```bash
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080
```

Open `http://127.0.0.1:8080/`.

Completed audio files are written to `downloads/`.
