"""Local-only transcription UI. One GPU job at a time; no sudo/system pip."""
from __future__ import annotations

import gc
import json
import os
import queue
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from decoder import decode_to_memmap

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from opencc import OpenCC

ROOT = Path(__file__).resolve().parent
STORE = ROOT / "data" / "jobs"
STORE.mkdir(parents=True, exist_ok=True)
LIMIT = int(os.getenv("MAX_UPLOAD_GB", "2")) * 1024 ** 3
MAX_QUEUE = int(os.getenv("MAX_QUEUE", "3"))
LANG = {"auto": None, "zh": "zh", "ja": "ja", "en": "en", "ko": "ko"}
MODELS = {"small", "medium", "large-v3", "turbo"}
EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".mp3",
       ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus"}
JOBS = {}
Q = queue.Queue()
LOCK = threading.RLock()
app = FastAPI(title="Whisper Web UI", docs_url=None, redoc_url=None)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fmt(seconds, comma=True):
    millis = max(0, round(float(seconds) * 1000))
    h, rest = divmod(millis, 3600000)
    m, rest = divmod(rest, 60000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{',' if comma else '.'}{ms:03d}"


def save(item):
    folder = STORE / item["id"]
    tmp = folder / "job.tmp"
    tmp.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(folder / "job.json")


def update(jid, **changes):
    with LOCK:
        item = JOBS[jid]
        item.update(changes)
        item["updated_at"] = stamp()
        save(item)


def public(item):
    return {key: value for key, value in item.items() if key != "extension"}


def transcribe(jid):
    from faster_whisper import WhisperModel

    with LOCK:
        item = dict(JOBS[jid])
    model = None
    audio = None
    scratch = STORE / jid / "decoded.pcm"
    try:
        update(jid, status="processing", progress=1, message="載入模型，首次可能需下載…")
        model = WhisperModel(
            item["model"],
            device="cuda",
            compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8_float16"),
            cpu_threads=max(1, int(os.getenv("WHISPER_CPU_THREADS", "2"))),
            num_workers=1
        )
        media = STORE / jid / ("input" + item["extension"])
        update(jid, message="FFmpeg 解碼音訊，略過 PyAV")
        audio = decode_to_memmap(media, scratch)
        update(jid, message="正在使用 GPU 辨識")
        iterator, info = model.transcribe(
            audio, beam_size=5, language=LANG[item["language"]],
            vad_filter=item["vad"], condition_on_previous_text=False
        )
        duration = float(info.duration or 0)
        converter = OpenCC("s2twp") if info.language == "zh" else None
        srt, vtt, txt = [], ["WEBVTT", ""], []
        count = 0
        for segment in iterator:
            content = (segment.text or "").strip()
            if not content:
                continue
            if converter:
                content = converter.convert(content)
            start, end = float(segment.start), float(segment.end)
            count += 1
            srt.extend([str(count), fmt(start) + " --> " + fmt(end), content, ""])
            vtt.extend([fmt(start, False) + " --> " + fmt(end, False), content, ""])
            txt.append(content)
            progress = min(98, max(1, int(100 * end / max(1, duration))))
            update(jid, progress=progress, segments=count)
        folder = STORE / jid
        for name, lines in (("srt", srt), ("vtt", vtt), ("txt", txt)):
            (folder / ("subtitle." + name)).write_text(
                "\n".join(lines), encoding="utf-8-sig"
            )
        update(jid, status="done", progress=100, segments=count,
               detected_language=info.language, duration=duration,
               message="完成，可下載字幕")
    finally:
        del audio
        del model
        gc.collect()
        scratch.unlink(missing_ok=True)
        (STORE / jid / ("input" + item["extension"])).unlink(missing_ok=True)


def worker():
    while True:
        jid = Q.get()
        try:
            transcribe(jid)
        except Exception as exc:
            print(traceback.format_exc(), flush=True)
            update(jid, status="failed", message="處理失敗",
                   error=str(exc)[:300])
        finally:
            Q.task_done()


@app.on_event("startup")
def startup():
    # Clean orphaned uploads after an unclean shutdown, including queued jobs.
    # No worker is started yet, so nothing here is actively processing.
    for folder in STORE.iterdir():
        if not folder.is_dir():
            continue
        for source in folder.glob("input.*"):
            source.unlink(missing_ok=True)
        (folder / "decoded.pcm").unlink(missing_ok=True)
    for file in STORE.glob("*/job.json"):
        try:
            item = json.loads(file.read_text(encoding="utf-8"))
            if item["status"] in ("queued", "processing"):
                item["status"] = "failed"
                item["message"] = "服務重新啟動，請重新上傳"
                save(item)
            JOBS[item["id"]] = item
        except (OSError, ValueError, KeyError, TypeError):
            continue
    threading.Thread(target=worker, daemon=True, name="gpu-worker").start()


@app.get("/")
def index():
    return HTMLResponse((ROOT / "index.html").read_text(encoding="utf-8"))


@app.get("/api/jobs")
def list_jobs():
    with LOCK:
        return [public(item) for item in sorted(
            JOBS.values(), key=lambda x: x["created_at"], reverse=True
        )[:30]]


@app.post("/api/jobs", status_code=201)
async def upload(
    file: UploadFile = File(...),
    model: str = Form("small"),
    language: str = Form("auto"),
    vad: bool = Form(True)
):
    if model not in MODELS or language not in LANG:
        raise HTTPException(400, "模型或語言不支援")
    filename = (file.filename or "").replace("\\", "/").split("/")[-1][:160]
    extension = Path(filename).suffix.lower()
    if extension not in EXT:
        raise HTTPException(400, "不支援的影片或音訊格式")
    with LOCK:
        pending = sum(x["status"] in ("queued", "processing") for x in JOBS.values())
        if pending >= MAX_QUEUE:
            raise HTTPException(429, "佇列已滿")
    jid = uuid.uuid4().hex
    folder = STORE / jid
    folder.mkdir(parents=True, exist_ok=False)
    destination = folder / ("input" + extension)
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(4 * 1024 * 1024):
                size += len(chunk)
                if size > LIMIT:
                    raise HTTPException(413, "檔案超過上限")
                output.write(chunk)
        if not size:
            raise HTTPException(400, "空檔案")
    except Exception:
        destination.unlink(missing_ok=True)
        folder.rmdir()
        raise
    finally:
        await file.close()
    item = {
        "id": jid, "filename": filename, "extension": extension,
        "bytes": size, "model": model, "language": language, "vad": vad,
        "status": "queued", "progress": 0, "segments": 0,
        "detected_language": None, "duration": None,
        "message": "等待 GPU 工作佇列", "error": None,
        "created_at": stamp(), "updated_at": stamp()
    }
    with LOCK:
        JOBS[jid] = item
        save(item)
        Q.put(jid)
    return public(item)


@app.get("/api/jobs/{jid}/preview")
def preview(jid: str):
    with LOCK:
        item = JOBS.get(jid)
        if not item or item["status"] != "done":
            raise HTTPException(404, "字幕尚未完成")
    source = STORE / jid / "subtitle.txt"
    return {"text": source.read_text(encoding="utf-8-sig")[:20000]}


@app.get("/api/jobs/{jid}/download/{extension}")
def download(jid: str, extension: str):
    if extension not in ("srt", "vtt", "txt"):
        raise HTTPException(404, "格式不支援")
    with LOCK:
        item = JOBS.get(jid)
        if not item or item["status"] != "done":
            raise HTTPException(404, "字幕尚未完成")
    source = STORE / jid / ("subtitle." + extension)
    if not source.exists():
        raise HTTPException(404, "找不到字幕")
    return FileResponse(source, filename=Path(item["filename"]).stem + "." + extension)
