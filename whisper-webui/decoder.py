"""Decode uploaded audio using FFmpeg instead of the PyAV code path."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np


def decode_to_memmap(media: Path, scratch: Path):
    """Produce 16kHz mono float32 PCM on disk, bounded by MAX_PCM_MB.

    The returned NumPy memmap is accepted directly by faster-whisper and
    bypasses faster_whisper.audio.decode_audio / av.open entirely.
    """
    import imageio_ffmpeg

    ffmpeg = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
    max_bytes = max(64, int(os.getenv("MAX_PCM_MB", "512"))) * 1024 * 1024
    args = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-threads", "2", "-i", str(media), "-map", "0:a:0",
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_f32le",
        "-f", "f32le", "pipe:1",
    ]
    total = 0
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with scratch.open("wb") as target:
            while True:
                chunk = process.stdout.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(
                        "音訊解碼後超過限制（預設 512 MiB，約 2 小時 20 分鐘）。"
                        "若需延長可設定 MAX_PCM_MB。"
                    )
                target.write(chunk)
        process.stdout.close()
        error = process.stderr.read(4096).decode("utf-8", errors="replace")
        returncode = process.wait()
        if returncode != 0:
            raise RuntimeError("FFmpeg 無法解碼此影片的音訊：" + error[:400])
        if total == 0 or total % 4:
            raise ValueError("沒有讀取到有效音訊，或音訊格式異常")
        return np.memmap(scratch, mode="r", dtype=np.float32)
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait()
        raise
    finally:
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
