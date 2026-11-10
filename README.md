# yt-dlp Web GUI

繁體中文、本機優先的影片下載工作台。React + Tailwind CSS 前端與 Python FastAPI 後端分離，使用 yt-dlp 下載、FFmpeg 切割成**可獨立播放且各自不超過指定 MB** 的 MP4，並可重新合併。

## 功能

- 貼上 yt-dlp 支援的影片網址，選擇畫質，加入下載佇列
- 同時下載多個任務，設定平行任務數與分段下載連線數
- WebSocket 即時更新進度、下載速度、剩餘時間、處理狀態
- 可設定「下載完成後自動分割」，每份預設 **500 MB**；任務進行中（開始切割前）仍可修改大小
- 各段 MP4 可以獨立播放、下載；提供重新分割與合併按鈕
- 下載時間新到舊排序；SQLite 儲存歷史，支援取消／重試（可在來源允許時續傳）
- Windows 一鍵從檔案總管開啟下載目錄
- 不需要雲端帳號；預設僅監聽 127.0.0.1

## Windows 11 快速開始

1. 安裝 [Python 3.11+](https://www.python.org/downloads/)、[Node.js 20+](https://nodejs.org/)。
2. 以 PowerShell 安裝 FFmpeg：`winget install --id Gyan.FFmpeg -e`，安裝後重新開啟終端機，確認 `ffmpeg -version`、`ffprobe -version` 均能執行。
3. 下載本 Repository，解壓縮後，**雙擊 `start.bat`**。首次執行會建立 Python 虛擬環境、安裝套件、建置前端。
4. 瀏覽器會開啟 [http://127.0.0.1:8765](http://127.0.0.1:8765)。

> 如果執行政策或環境阻擋 bat，也可以從 PowerShell 執行 `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1`。

### 開發模式

後端（第一個終端機）：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8765 --reload
```

前端（第二個終端機）：

```powershell
cd frontend
npm install
npm run dev
```

開啟 [http://127.0.0.1:5173](http://127.0.0.1:5173)，Vite 自動代理 `/api` 及 `/ws` 到後端。

## MP4 切割原理

1. 先使用 FFmpeg `-c copy` 依關鍵影格切割，**不重新編碼、不損失原始影音串流品質**。
2. 如果某片超過設定大小，會自動縮短目標片長重試。
3. 若來源影片關鍵影格太少，無法無損切到大小限制，則使用 H.264 + AAC 對切割用的工作副本重新編碼，強制增加關鍵影格再重試。**此情況會有重新編碼的畫質損失**，但保留原始下載的 MP4。
4. 成功才把新切割結果放進 `parts/`。各片都是真正的 MP4，不是無法獨立播放的二進位碎片。
5. 「合併」使用 FFmpeg concat + `-c copy`，不再次重新編碼。封裝及時間戳可能不同，**不保證位元組與原片完全相同**。

若重編碼後依然無法保證嚴格大小限制，任務會顯示錯誤，而不是悄悄產出超標檔案。

## 資料保存

- 預設下載位置：`data/downloads/<task-id>/`
- 資料庫：`data/tasks.sqlite3`（下載紀錄與設定，重啟保留）
- 每個任務會保留原始 `video.mp4`、分割檔 `parts/part_000.mp4`...；按「合併」後產生 `merged.mp4`
- 可在設定中改變**新任務**的下載資料夾；舊任務保持原路徑，不會被搬動
- 當程式意外關閉，執行中的任務標為「已中斷」，可按「重試」恢復（yt-dlp 在來源允許時會使用殘留的 .part 檔續傳）

## 使用限制與安全

- 目前處理**單部影片**（預設禁止自動下載整份播放清單）。
- 下載完成可能需要額外的磁碟空間來保存原影片、切割檔、重編碼工作副本與合併檔。
- Windows「開啟檔案總管」是在**執行後端的那台 Windows 電腦**操作。將後端架設在遠端伺服器時，不能打開另一台電腦的本機檔案總管。
- 只適合**個人本機執行**。API 未設登入，不要改成 `0.0.0.0` 對外公開。
- 下載請遵守網站服務條款及著作權規定。需要登入或 DRM 保護的影片不保證可下載。

## 測試

```bash
python -m compileall backend
python -m unittest discover -s backend/tests -v
cd frontend && npm install && npm run build
```

測試切割／合併需要系統裝有 FFmpeg；相關 CI 使用 GitHub Actions 進行驗證。
