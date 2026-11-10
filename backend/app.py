"""Local yt-dlp download manager. Run with: uvicorn app:app --app-dir backend."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("YTDLP_GUI_DATA", ROOT / "data")).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "tasks.sqlite3"
MAX_WORKERS = 4
pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="download")
lock = threading.RLock()
active: dict[str, threading.Event] = {}
running_processes: dict[str, subprocess.Popen] = {}
STOPPED = {"completed", "cancelled", "failed", "interrupted"}
app = FastAPI(title="yt-dlp Web GUI", version="0.1.0")


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    connection = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def initialize():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
          status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '',
          progress REAL NOT NULL DEFAULT 0, speed REAL NOT NULL DEFAULT 0,
          eta REAL, size_bytes INTEGER NOT NULL DEFAULT 0,
          downloaded_bytes INTEGER NOT NULL DEFAULT 0,
          split_mb INTEGER NOT NULL DEFAULT 500, auto_split INTEGER NOT NULL DEFAULT 1,
          quality TEXT NOT NULL DEFAULT 'best',
          folder TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        )""")
        db.execute("UPDATE tasks SET status='interrupted',stage='已中斷，可按重試' WHERE status IN ('downloading','processing','splitting','merging')")
        db.execute("UPDATE tasks SET status='interrupted',stage='程式重啟，請按重試' WHERE status='queued'")
        db.execute("INSERT OR IGNORE INTO settings VALUES ('max_concurrent','2')")
        db.execute("INSERT OR IGNORE INTO settings VALUES ('fragments','4')")


initialize()


def query_one(task_id):
    with lock, connect() as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None


def list_tasks():
    with lock, connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM tasks ORDER BY created_at DESC, rowid DESC")]


def setting(key, default):
    with lock, connect() as db:
        r = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default


def patch(task_id, **changes):
    if not changes:
        return
    allowed = {"title","status","stage","progress","speed","eta","size_bytes",
               "downloaded_bytes","split_mb","auto_split","quality","error"}
    if not changes.keys() <= allowed:
        raise ValueError("Invalid update")
    changes["updated_at"] = now()
    with lock, connect() as db:
        db.execute("UPDATE tasks SET " + ",".join(f"{k}=?" for k in changes) +
                   " WHERE id=?", (*changes.values(), task_id))


def folder_for(task_id):
    row = query_one(task_id)
    if not row:
        raise HTTPException(404, "找不到任務")
    return Path(row["folder"])


def ffmpeg_ok():
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def execute(cmd: list[str], task_id: str | None = None, cwd=None):
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, creationflags=flags)
    if task_id:
        with lock:
            running_processes[task_id] = proc
    try:
        while proc.poll() is None:
            if task_id and active.get(task_id) and active[task_id].is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise Cancelled("使用者取消任務")
            time.sleep(0.2)
        err = proc.stderr.read().decode("utf-8", errors="replace")[-2500:]
        if proc.returncode:
            raise RuntimeError(f"FFmpeg 失敗：{err}")
    finally:
        if task_id:
            with lock:
                if running_processes.get(task_id) is proc:
                    running_processes.pop(task_id, None)
        if proc.stderr:
            proc.stderr.close()


class Cancelled(Exception):
    pass


def probe_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def make_mp4(source: Path, destination: Path, task_id: str):
    if source == destination:
        return
    try:
        execute(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                 "-map", "0:v:0", "-map", "0:a?", "-c", "copy",
                 "-movflags", "+faststart", str(destination)], task_id)
    except RuntimeError:
        destination.unlink(missing_ok=True)
        execute(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                 "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264",
                 "-preset", "fast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                 "-movflags", "+faststart", str(destination)], task_id)


def split_video(task_id: str, max_mb: int):
    if not ffmpeg_ok():
        raise RuntimeError("找不到 FFmpeg / ffprobe，請先安裝並重新啟動程式")
    folder = folder_for(task_id)
    video = folder / "video.mp4"
    if not video.exists():
        raise RuntimeError("找不到 video.mp4，無法分割")
    limit = max_mb * 1_000_000
    duration = probe_duration(video)
    if duration <= 0:
        raise RuntimeError("影片長度無效")
    work = folder / ".split_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    encoded = work / "encoded.mp4"
    source = video
    try:
        for mode in ("copy", "encode"):
            if mode == "encode":
                patch(task_id, stage="無損切割無法達到大小上限，正在重新編碼", progress=0)
                execute(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                         "-i", str(video), "-map", "0:v:0", "-map", "0:a?",
                         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                         "-force_key_frames", "expr:gte(t,n_forced*2)",
                         "-c:a", "aac", "-b:a", "160k", str(encoded)], task_id)
                source = encoded
            size = source.stat().st_size
            seconds = max(0.25, duration * (limit * 0.86 / max(size, 1)))
            for attempt in range(12):
                if active.get(task_id) and active[task_id].is_set():
                    raise Cancelled("使用者取消")
                for part in work.glob("part_*.mp4"):
                    part.unlink()
                (work / "parts.ffconcat").unlink(missing_ok=True)
                patch(task_id, stage=f"切割 MP4（{mode}，第 {attempt+1} 次）",
                      progress=min(95, (attempt + (0 if mode == "copy" else 12)) * 3))
                execute(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                         "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
                         "-c", "copy", "-f", "segment",
                         "-segment_time", f"{seconds:.4f}", "-reset_timestamps", "1",
                         "-segment_list", str(work / "parts.ffconcat"),
                         "-segment_list_type", "ffconcat",
                         str(work / "part_%03d.mp4")], task_id)
                parts = sorted(work.glob("part_*.mp4"))
                if not parts:
                    raise RuntimeError("FFmpeg 沒有產生任何片段")
                biggest = max(p.stat().st_size for p in parts)
                if biggest <= limit:
                    target = folder / "parts"
                    previous = folder / ".parts_previous"
                    if previous.exists():
                        shutil.rmtree(previous)
                    if target.exists():
                        target.rename(previous)
                    target.mkdir()
                    try:
                        for part in parts:
                            part.rename(target / part.name)
                        concat = "ffconcat version 1.0\n" + "".join(
                            f"file '{p.name}'\n" for p in parts)
                        (target / "parts.ffconcat").write_text(concat, encoding="utf-8")
                        (target / "meta.json").write_text(json.dumps({
                            "split_mb": max_mb, "mode": mode,
                            "count": len(parts)}, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        shutil.rmtree(target, ignore_errors=True)
                        if previous.exists():
                            previous.rename(target)
                        raise
                    shutil.rmtree(previous, ignore_errors=True)
                    return len(parts), mode
                seconds *= min(0.78, limit * 0.8 / biggest)
                if seconds < 0.05:
                    break
        raise RuntimeError("無法讓所有 MP4 片段低於指定大小；請調大 MB 或改用其他影片")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def find_video(folder):
    output = folder / "video.mp4"
    if output.exists():
        return output
    candidates = [p for p in folder.glob("source.*")
                  if p.suffix.lower() not in {".part",".ytdl",".json",".txt"} and p.is_file()]
    if not candidates:
        raise RuntimeError("下載完成但找不到影片檔")
    return max(candidates, key=lambda p: p.stat().st_size)


def download(task_id, stop):
    row = query_one(task_id)
    folder = Path(row["folder"])
    folder.mkdir(parents=True, exist_ok=True)
    if not ffmpeg_ok():
        raise RuntimeError("找不到 FFmpeg / ffprobe，請先安裝")
    patch(task_id, status="downloading", stage="下載中", progress=0, error="")
    last_update = [0.0]

    def hook(event):
        if stop.is_set():
            raise Cancelled("使用者取消")
        if event.get("status") == "downloading":
            tick = time.monotonic()
            if tick - last_update[0] < 0.25:
                return
            last_update[0] = tick
            done = int(event.get("downloaded_bytes") or 0)
            total = int(event.get("total_bytes") or event.get("total_bytes_estimate") or 0)
            patch(task_id, downloaded_bytes=done, size_bytes=total,
                  progress=round(100 * done / total, 1) if total else 0,
                  speed=int(event.get("speed") or 0), eta=event.get("eta"))
        elif event.get("status") == "finished":
            patch(task_id, stage="下載完成，準備封裝 MP4", progress=100, speed=0, eta=0)

    quality = row["quality"]
    if quality == "best":
        fmt = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
    else:
        fmt = f"bv*[height<={quality}][ext=mp4]+ba[ext=m4a]/b[height<={quality}][ext=mp4]/bv*[height<={quality}]+ba/b"
    opts = {
        "format": fmt, "outtmpl": str(folder / "source.%(ext)s"),
        "merge_output_format": "mp4", "noplaylist": True,
        "continuedl": True, "nopart": False,
        "concurrent_fragment_downloads": max(1, min(16, int(setting("fragments", "4")))),
        "progress_hooks": [hook], "quiet": True, "no_warnings": True,
        "restrictfilenames": True, "overwrites": False,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(row["url"], download=True)
            if info and info.get("title"):
                patch(task_id, title=str(info["title"])[:300])
    except Exception:
        if stop.is_set():
            raise Cancelled("下載已取消")
        raise
    if stop.is_set():
        raise Cancelled("下載已取消")
    patch(task_id, status="processing", stage="正在建立 MP4", progress=100)
    source = find_video(folder)
    make_mp4(source, folder / "video.mp4", task_id)
    if row["auto_split"]:
        # Read latest setting: user can edit size while downloading.
        current = query_one(task_id)
        patch(task_id, status="splitting", stage="準備分割 MP4", progress=0)
        count, mode = split_video(task_id, current["split_mb"])
        patch(task_id, status="completed", stage=f"完成，{count} 段 MP4（{mode}）", progress=100)
    else:
        patch(task_id, status="completed", stage="下載完成（未分割）", progress=100)


def process(task_id: str, stop: threading.Event):
    try:
        download(task_id, stop)
    except Cancelled:
        patch(task_id, status="cancelled", stage="已取消", speed=0, eta=None)
    except Exception as exc:
        patch(task_id, status="failed", stage="發生錯誤", speed=0,
              eta=None, error=str(exc)[:1500])
    finally:
        with lock:
            active.pop(task_id, None)


def start_next():
    with lock:
        limit = max(1, min(MAX_WORKERS, int(setting("max_concurrent", "2"))))
        free = limit - len(active)
        if free <= 0:
            return
        with connect() as db:
            queued = [r["id"] for r in db.execute(
                "SELECT id FROM tasks WHERE status='queued' ORDER BY created_at ASC LIMIT ?",
                (free,))]
        for task_id in queued:
            stop = threading.Event()
            active[task_id] = stop
            pool.submit(process, task_id, stop)


def scheduler():
    while True:
        try:
            start_next()
        except Exception as exc:
            print("Scheduler error:", exc, file=sys.stderr)
        time.sleep(0.5)


threading.Thread(target=scheduler, daemon=True, name="queue-scheduler").start()


class NewTask(BaseModel):
    url: str = Field(min_length=8, max_length=4096)
    split_mb: int = Field(default=500, ge=10, le=50000)
    auto_split: bool = True
    quality: str = "best"


class UpdateTask(BaseModel):
    split_mb: int = Field(ge=10, le=50000)
    auto_split: bool | None = None


class SettingsBody(BaseModel):
    max_concurrent: int = Field(ge=1, le=4)
    fragments: int = Field(ge=1, le=16)


@app.get("/api/health")
def health():
    return {"ok": True, "ffmpeg": ffmpeg_ok(), "version": "0.1.0"}


@app.get("/api/tasks")
def tasks():
    return list_tasks()


@app.post("/api/tasks")
def add_task(body: NewTask):
    parsed = urlparse(body.url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "網址必須以 http:// 或 https:// 開頭")
    if body.quality not in {"best", "2160", "1440", "1080", "720", "480", "360"}:
        raise HTTPException(400, "無效畫質")
    task_id = str(uuid.uuid4())
    folder = DATA / "downloads" / task_id
    with lock, connect() as db:
        db.execute("""INSERT INTO tasks
            (id,url,title,status,stage,split_mb,auto_split,quality,folder,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, body.url, parsed.hostname, "queued", "排隊中",
             body.split_mb, int(body.auto_split), body.quality, str(folder), now(), now()))
    return query_one(task_id)


@app.patch("/api/tasks/{task_id}")
def change_task(task_id: str, body: UpdateTask):
    row = query_one(task_id)
    if not row:
        raise HTTPException(404, "找不到任務")
    if row["status"] in {"splitting", "processing", "merging"}:
        raise HTTPException(409, "影片處理中無法變更分割設定")
    changes = {"split_mb": body.split_mb}
    if body.auto_split is not None:
        changes["auto_split"] = int(body.auto_split)
    patch(task_id, **changes)
    return query_one(task_id)


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    row = query_one(task_id)
    if not row:
        raise HTTPException(404, "找不到任務")
    if row["status"] == "queued":
        patch(task_id, status="cancelled", stage="已取消")
    elif row["status"] in {"downloading", "processing", "splitting"}:
        with lock:
            if task_id in active:
                active[task_id].set()
        patch(task_id, stage="正在取消…")
    else:
        raise HTTPException(409, "目前狀態無法取消")
    return query_one(task_id)


@app.post("/api/tasks/{task_id}/retry")
def retry_task(task_id: str):
    row = query_one(task_id)
    if not row:
        raise HTTPException(404, "找不到任務")
    if row["status"] not in {"cancelled", "failed", "interrupted"}:
        raise HTTPException(409, "只有取消、失敗或中斷的任務可以重試")
    with lock:
        if task_id in active:
            raise HTTPException(409, "前一個任務尚未結束")
        patch(task_id, status="queued", stage="排隊中", error="", progress=0)
    return query_one(task_id)


def run_postprocess(task_id, action):
    # Prevent two operations on same task.
    with lock:
        row = query_one(task_id)
        if not row:
            raise HTTPException(404, "找不到任務")
        if task_id in active or row["status"] not in STOPPED:
            raise HTTPException(409, "任務仍在進行中")
        if not (Path(row["folder"]) / "video.mp4").is_file():
            raise HTTPException(404, "找不到已下載的 MP4")
        stop = threading.Event()
        active[task_id] = stop
        patch(task_id, status="splitting" if action == "split" else "merging",
              stage="處理中", progress=0, error="")

    def job():
        try:
            folder = folder_for(task_id)
            if action == "split":
                count, mode = split_video(task_id, query_one(task_id)["split_mb"])
                stage = f"分割完成，{count} 段（{mode}）"
            else:
                concat = folder / "parts" / "parts.ffconcat"
                if not concat.exists():
                    raise RuntimeError("尚未分割，無法合併")
                output = folder / "merged.mp4"
                temp = folder / ".merged.tmp.mp4"
                temp.unlink(missing_ok=True)
                execute(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                         "-f", "concat", "-safe", "0", "-i", str(concat),
                         "-map", "0", "-c", "copy", "-movflags", "+faststart",
                         str(temp)], task_id)
                temp.replace(output)
                stage = "分段合併完成"
            patch(task_id, status="completed", progress=100, stage=stage)
        except Cancelled:
            patch(task_id, status="cancelled", stage="已取消")
        except Exception as exc:
            patch(task_id, status="failed", stage="處理失敗", error=str(exc)[:1500])
        finally:
            with lock:
                active.pop(task_id, None)
    pool.submit(job)


@app.post("/api/tasks/{task_id}/split")
def split_again(task_id: str):
    run_postprocess(task_id, "split")
    return {"ok": True}


@app.post("/api/tasks/{task_id}/merge")
def merge(task_id: str):
    run_postprocess(task_id, "merge")
    return {"ok": True}


@app.get("/api/tasks/{task_id}/files")
def files(task_id: str):
    folder = folder_for(task_id)
    paths = [folder / "video.mp4", folder / "merged.mp4"]
    paths += sorted((folder / "parts").glob("part_*.mp4")) if (folder / "parts").exists() else []
    return [{"name": p.name, "size": p.stat().st_size,
             "url": f"/api/tasks/{task_id}/file/{'parts/' if p.parent.name == 'parts' else ''}{p.name}"}
            for p in paths if p.is_file()]


@app.get("/api/tasks/{task_id}/file/{filename:path}")
def file(task_id: str, filename: str):
    folder = folder_for(task_id)
    if filename not in {"video.mp4", "merged.mp4"} and not (
        filename.startswith("parts/") and
        filename[6:].startswith("part_") and
        filename.endswith(".mp4") and
        "/" not in filename[6:] and "\\" not in filename
    ):
        raise HTTPException(400, "不允許的檔案路徑")
    target = (folder / filename).resolve()
    if not target.is_file() or not target.is_relative_to(folder.resolve()):
        raise HTTPException(404, "檔案不存在")
    return FileResponse(target, media_type="video/mp4", filename=target.name)


@app.post("/api/tasks/{task_id}/open-folder")
def open_folder(task_id: str):
    folder = folder_for(task_id)
    if os.name != "nt":
        raise HTTPException(400, "僅能在執行後端的 Windows 電腦開啟檔案總管")
    if not folder.exists():
        raise HTTPException(404, "資料夾尚未建立")
    subprocess.Popen(["explorer.exe", str(folder)])
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    return {"max_concurrent": int(setting("max_concurrent", "2")),
            "fragments": int(setting("fragments", "4"))}


@app.put("/api/settings")
def update_settings(body: SettingsBody):
    with lock, connect() as db:
        for key, val in body.model_dump().items():
            db.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                       (key, str(val)))
    return get_settings()


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    # Only local use; reject browser connections from unrelated Origins.
    origin = ws.headers.get("origin", "")
    if origin:
        host = urlparse(origin).hostname
        if host not in {"localhost", "127.0.0.1"}:
            await ws.close(code=1008)
            return
    await ws.accept()
    try:
        while True:
            await ws.send_json({"tasks": list_tasks()})
            await asyncio.sleep(0.75)
    except (WebSocketDisconnect, RuntimeError):
        pass


# Serve production frontend when npm run build has completed.
from fastapi.staticfiles import StaticFiles
DIST = ROOT / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
