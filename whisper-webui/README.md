# Whisper Web UI (L40S, uv)

A lightweight, local-only Python web interface to upload video/audio and generate **SRT / VTT / TXT** with faster-whisper on NVIDIA CUDA GPU.

## Linux setup (no sudo, project isolated)

```bash
git clone https://github.com/KKacobls/yt-dlp-web-gui.git
cd yt-dlp-web-gui/whisper-webui
bash setup.sh
./run.sh
```

The installer uses `uv`, installs Python 3.12 into this project if needed, and installs packages into `.venv`. No system Python or global pip changes.

Connect using SSH port forwarding or VS Code Remote SSH forwarding port **17860**. Open `http://127.0.0.1:17860` on your computer. The web server listens on loopback only (no authentication); **do not expose it on a public interface**.

Default small model, int8_float16, CPU threads=2, single GPU job worker, max 3 queued/processing jobs, 2 GiB upload cap. Original upload is deleted when processed; results persist under `data/jobs`. First run downloads model weights into `models`.

**Shared server caution:** uv isolates dependencies but does not cap GPU utilization or memory. Use while GPU is available and ask your administrator before large models. Only use this on trusted shared machines because localhost is reachable by other local users.

To stop: Ctrl+C. To remove environment: delete the `whisper-webui` directory.
