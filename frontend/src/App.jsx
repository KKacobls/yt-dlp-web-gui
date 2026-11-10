import React, { useEffect, useState, useCallback } from 'react';
import { Download, Link2, CheckCircle2, Clock3, FolderOpen, Scissors, Layers, RotateCcw, Square, Play, ExternalLink, HardDrive, Activity, Settings, RefreshCcw, FileVideo, Wifi, WifiOff, Plus, X, Check, LoaderCircle, Moon, Sun } from 'lucide-react';
import './styles.css';

const api = async (path, options={}) => {
  const response = await fetch('/api'+path, { headers: {'Content-Type':'application/json'}, ...options });
  const data = await response.json().catch(()=>({}));
  if (!response.ok) throw new Error(data.detail || 'HTTP error '+response.status);
  return data;
};
const post = path => api(path, {method:'POST'});
const human = n => n ? (n/1e6).toFixed(1)+' MB' : '—';
const stateLabels = {
  queued:['排隊中','bg-amber-50 text-amber-700'],downloading:['下載中','bg-indigo-50 text-indigo-700'],
  processing:['處理中','bg-blue-50 text-blue-700'],splitting:['分割中','bg-blue-50 text-blue-700'],
  merging:['合併中','bg-blue-50 text-blue-700'],completed:['已完成','bg-emerald-50 text-emerald-700'],
  cancelled:['已取消','bg-slate-100 text-slate-500'],failed:['失敗','bg-rose-50 text-rose-700'],
  interrupted:['已中斷','bg-orange-50 text-orange-700']
};
const running = ['queued','downloading','processing','splitting','merging'];

function Task({item,act,notice}) {
  const [show,setShow] = useState(false);
  const [files,setFiles] = useState([]);
  const [edit,setEdit] = useState(false);
  const [size,setSize] = useState(item.split_mb);
  const [busy,setBusy] = useState(false);
  const refresh = useCallback(() => {
    api('/tasks/'+item.id+'/files').then(setFiles).catch(e=>notice(e.message,true));
  },[item.id,notice]);
  useEffect(()=>{ if(show) refresh(); },[show,item.stage,refresh]);
  useEffect(()=>{if(!edit)setSize(item.split_mb)},[item.split_mb,edit]);
  const status=stateLabels[item.status]||stateLabels.queued;
  const progress=Math.max(0,Math.min(100,Number(item.progress)||0));
  async function perform(name) {
    setBusy(true);
    try { await act(item.id,name); if(name==='split'||name==='merge')setShow(true); }
    finally {setBusy(false);}
  }
  async function save() {
    if(!Number.isInteger(Number(size))||Number(size)<10||Number(size)>50000){
      notice('大小需介於 10～50000 MB',true);return;
    }
    try{
      await api('/tasks/'+item.id,{method:'PATCH',body:JSON.stringify({split_mb:Number(size)})});
      setEdit(false);notice('分割大小已儲存');
    }catch(e){notice(e.message,true);}
  }
  return <article className="card overflow-hidden">
    <div className="p-5 sm:p-6">
      <div className="flex items-start gap-4">
        <div className="w-[64px] h-[64px] flex-none rounded-xl bg-gradient-to-br from-violet-100 to-indigo-100 flex items-center justify-center text-violet-500"><FileVideo size={28}/></div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap gap-2 justify-between">
            <h3 className="font-bold text-slate-900 break-words max-w-full">{item.title}</h3>
            <span className={'text-xs font-bold rounded-lg px-2.5 py-1.5 h-fit '+status[1]}>{status[0]}</span>
          </div>
          <a href={item.url} rel="noreferrer" target="_blank" className="flex items-center gap-1 mt-1.5 text-xs text-slate-400 hover:text-indigo-600 max-w-full"><Link2 size={12} className="flex-none"/><span className="truncate">{item.url}</span></a>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-xs text-slate-500">
            <span><Clock3 size={12} className="inline"/> {new Date(item.created_at).toLocaleString('zh-TW')}</span>
            <span><HardDrive size={12} className="inline"/> {human(item.size_bytes)}</span>
            <span><Scissors size={12} className="inline"/> {item.auto_split?item.split_mb+' MB / 段':'不自動分割'}</span>
            <span>畫質：{item.quality==='best'?'最佳':item.quality+'p'}</span>
          </div>
        </div>
      </div>
      {running.includes(item.status)&&<div className="mt-5">
        <div className="flex justify-between gap-2 text-sm mb-2"><span className="font-medium truncate">{item.stage}</span><b className="text-indigo-600">{progress.toFixed(1)}%</b></div>
        <div className="progress-bg"><div className="progress-bar" style={{width:progress+'%'}}/></div>
        <div className="flex justify-between mt-2 text-xs text-slate-400">
          <span>{item.status==='downloading'?human(item.downloaded_bytes)+' / '+human(item.size_bytes):'處理影片中'}</span>
          <span>{item.status==='downloading'?(item.speed?(item.speed/1e6).toFixed(1)+' MB/s':'—')+' · '+(item.eta||'—')+' 秒':''}</span>
        </div>
      </div>}
      {item.error&&<div className="bg-rose-50 text-rose-700 text-xs p-3 mt-4 rounded-lg break-all">{item.error}</div>}
      <div className="flex flex-wrap items-center gap-2 mt-5 pt-4 border-t border-slate-100">
        <button className="btn-ghost !px-3 !py-2" onClick={()=>setShow(!show)}><FolderOpen size={16}/> {show?'收起檔案':'查看檔案'}</button>
        <button className="btn-ghost !px-3 !py-2" disabled={busy} onClick={()=>perform('open-folder')}><ExternalLink size={15}/> 檔案總管</button>
        {item.status==='completed'&&<>
          <button className="btn-ghost !px-3 !py-2" disabled={busy} onClick={()=>perform('split')}><Scissors size={15}/> 分割</button>
          <button className="btn-ghost !px-3 !py-2" disabled={busy} onClick={()=>perform('merge')}><Layers size={15}/> 合併</button>
        </>}
        {['failed','cancelled','interrupted'].includes(item.status)&&<button className="btn-ghost !px-3 !py-2" disabled={busy} onClick={()=>perform('retry')}><RotateCcw size={15}/> 重試</button>}
        {running.includes(item.status)&&<button className="btn-ghost !px-3 !py-2 !text-rose-600" disabled={busy} onClick={()=>perform('cancel')}><Square size={14}/> 取消</button>}
        <div className="ml-auto">
          {edit?<span className="flex items-center gap-1"><input className="field !w-24 !p-2" type="number" min="10" max="50000" value={size} onChange={e=>setSize(e.target.value)}/><span className="text-xs">MB</span><button className="icon-btn" onClick={save}><Check size={17}/></button><button className="icon-btn" onClick={()=>setEdit(false)}><X size={17}/></button></span>:
          <button disabled={['splitting','processing','merging'].includes(item.status)} className="text-xs font-semibold text-indigo-600 hover:underline" onClick={()=>setEdit(true)}>修改大小</button>}
        </div>
      </div>
    </div>
    {show&&<div className="bg-slate-50 px-5 py-4 border-t border-slate-100">
      <div className="flex justify-between items-center mb-2 text-xs text-slate-500 font-bold"><span>輸出 MP4</span><button onClick={refresh} className="icon-btn"><RefreshCcw size={15}/></button></div>
      {files.length?files.map(f=><div key={f.url} className="flex items-center gap-3 px-3 py-2 rounded-xl bg-white border border-slate-100 mb-2">
        <FileVideo size={17} className="text-indigo-500"/><span className="text-sm font-semibold flex-1 min-w-0 truncate">{f.name}</span><span className="text-xs text-slate-400">{human(f.size)}</span>
        <a className="icon-btn" href={f.url} target="_blank" rel="noreferrer" title="播放"><Play size={17}/></a>
        <a className="icon-btn" href={f.url} download title="下載"><Download size={17}/></a>
      </div>):<p className="text-sm text-slate-400 py-3">尚無 MP4 檔案</p>}
    </div>}
  </article>;
}

export default function App(){
  const [page,setPage]=useState('dashboard');
  const [tasks,setTasks]=useState([]);
  const [connected,setConnected]=useState(false);
  const [health,setHealth]=useState({});
  const [settings,setSettings]=useState({max_concurrent:2,fragments:4});
  const [url,setUrl]=useState('');
  const [quality,setQuality]=useState('best');
  const [splitMb,setSplitMb]=useState(500);
  const [autoSplit,setAutoSplit]=useState(true);
  const [filter,setFilter]=useState('all');
  const [loading,setLoading]=useState(false);
  const [toast,setToast]=useState(null);
  const [theme,setTheme]=useState(() => document.documentElement.classList.contains('dark') ? 'dark' : 'light');
  const notice=useCallback((message,error=false)=>setToast({message,error}),[]);
  useEffect(()=>{if(!toast)return;const id=setTimeout(()=>setToast(null),4500);return()=>clearTimeout(id)},[toast]);
  useEffect(()=>{
    const dark = theme === 'dark';
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0b1120' : '#f5f7fb');
    try { localStorage.setItem('ytdlp-theme', theme); } catch {}
  },[theme]);
  useEffect(()=>{
    api('/health').then(setHealth).catch(()=>{});
    api('/settings').then(setSettings).catch(()=>{});
    let ws,timeout,tries=0,alive=true;
    function connect(){
      if(!alive)return;
      ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
      ws.onopen=()=>{setConnected(true);tries=0};
      ws.onmessage=e=>{try{setTasks(JSON.parse(e.data).tasks||[])}catch{}};
      ws.onerror=()=>ws.close();
      ws.onclose=()=>{if(alive){setConnected(false);timeout=setTimeout(connect,Math.min(12000,1000*Math.pow(2,tries++)))}};
    }
    connect();return()=>{alive=false;clearTimeout(timeout);ws?.close()};
  },[]);
  const active=tasks.filter(t=>running.includes(t.status)).length;
  const completed=tasks.filter(t=>t.status==='completed').length;
  const filtered=tasks.filter(t=>filter==='all'||(filter==='active'&&running.includes(t.status))||(filter==='completed'&&t.status==='completed')||(filter==='other'&&['failed','cancelled','interrupted'].includes(t.status)));
  async function create(e){
    e.preventDefault();setLoading(true);
    try{
      await api('/tasks',{method:'POST',body:JSON.stringify({url:url.trim(),quality,split_mb:Number(splitMb),auto_split:autoSplit})});
      setUrl('');setFilter('all');setPage('dashboard');notice('已加入下載佇列');
    }catch(e){notice(e.message,true)}
    finally{setLoading(false)}
  }
  async function action(id,name){
    try{await post('/tasks/'+id+'/'+name);notice(name==='open-folder'?'已開啟檔案總管':name==='cancel'?'正在取消':name==='retry'?'已重新排隊':name==='split'?'開始分割':'開始合併')}
    catch(e){notice(e.message,true)}
  }
  async function saveSettings(){
    try{setSettings(await api('/settings',{method:'PUT',body:JSON.stringify(settings)}));notice('設定已儲存')}
    catch(e){notice(e.message,true)}
  }
  const nav=[['dashboard','下載總覽',Download],['history','下載紀錄',Clock3],['settings','偏好設定',Settings]];
  return <div className="flex min-h-screen">
    <aside className="hidden lg:flex w-64 bg-white border-r border-slate-100 min-h-screen sticky top-0 h-screen p-6 flex-col flex-none">
      <div className="flex items-center gap-3 mb-12 mt-2">
        <div className="w-11 h-11 rounded-xl bg-indigo-600 text-white flex items-center justify-center"><Download size={23}/></div>
        <div><div className="text-lg font-extrabold tracking-tight">yt-dlp <span className="text-indigo-600">Studio</span></div><p className="text-[10px] tracking-wider text-slate-400">DOWNLOAD WORKSPACE</p></div>
      </div>
      <p className="text-xs font-bold tracking-widest text-slate-400 px-3 mb-3">工作區</p>
      {nav.map(([key,label,Icon])=><button key={key} onClick={()=>setPage(key)} className={'flex items-center gap-3 p-3 text-sm font-semibold rounded-xl text-left mb-1 '+(page===key?'tab-active':'text-slate-500 hover:bg-slate-50')}><Icon size={18}/>{label}</button>)}
      <div className="mt-auto"><div className="rounded-xl bg-indigo-50 p-4 text-sm"><b className="text-indigo-700">本機下載工作台</b><p className="text-xs text-slate-500 mt-2 leading-5">任務與影片儲存在你的電腦，無須雲端帳號。</p></div>
      <p className="flex items-center gap-2 text-xs text-slate-400 mt-5">{connected?<Wifi size={15} className="text-emerald-500"/>:<WifiOff size={15} className="text-rose-500"/>}{connected?'即時連線正常':'正在重新連線'}</p></div>
    </aside>
    <main className="flex-1 min-w-0 max-w-[1450px] mx-auto px-4 sm:px-8 xl:px-12 py-8">
      <header className="flex items-center justify-between gap-2 mb-7">
        <div className="hidden lg:block text-xs text-slate-400">WORKSPACE / <span className="text-slate-700">{nav.find(n=>n[0]===page)?.[1]}</span></div>
        <div className="font-extrabold text-lg lg:hidden">yt-dlp <span className="text-indigo-600">Studio</span></div>
        <div className="flex items-center gap-2 sm:gap-3 text-xs font-semibold text-slate-500">
          <span className={'hidden sm:inline-flex px-3 py-1.5 rounded-full '+(connected?'bg-emerald-50 text-emerald-700':'bg-rose-50 text-rose-700')}>{connected?'● 系統已連線':'● 離線中'}</span>
          <button type="button" className="btn-ghost !px-3 !py-2" aria-pressed={theme==='dark'} aria-label={theme==='dark'?'切換淺色模式':'切換深色模式'} title={theme==='dark'?'切換淺色模式':'切換深色模式'} onClick={()=>setTheme(current=>current==='dark'?'light':'dark')}>
            {theme==='dark'?<Sun size={17}/>:<Moon size={17}/>}
            <span>{theme==='dark'?'淺色模式':'深色模式'}</span>
          </button>
          <button className="icon-btn" aria-label="偏好設定" title="偏好設定" onClick={()=>setPage('settings')}><Settings size={19}/></button>
        </div>
      </header>
      <div className="flex lg:hidden gap-2 mb-7">{nav.map(([key,label])=><button key={key} onClick={()=>setPage(key)} className={'btn !px-3 '+(page===key?'bg-indigo-600 text-white':'bg-white border text-slate-500')}>{label}</button>)}</div>
      <h1 className="font-extrabold text-3xl sm:text-4xl tracking-tight">{page==='settings'?'偏好設定':page==='history'?'下載紀錄':'你的下載工作台'}<span className="text-indigo-600">.</span></h1>
      <p className="text-slate-500 mt-2 mb-8 text-sm">{page==='settings'?'調整下載任務的運作方式。':page==='history'?'最新加入的任務顯示在最上面。':'輸入影片網址，下載、分割、合併，一個地方完成。'}</p>
      {page==='settings'?<div className="card p-6 max-w-xl">
        <h2 className="font-bold text-lg mb-6">下載設定</h2>
        <label className="block text-sm font-semibold mb-5">同時下載任務數
          <select className="field mt-2" value={settings.max_concurrent} onChange={e=>setSettings({...settings,max_concurrent:Number(e.target.value)})}>{[1,2,3,4].map(v=><option key={v} value={v}>{v} 部</option>)}</select>
        </label>
        <label className="block text-sm font-semibold mb-5">同一影片的並行片段數（網站支援時）
          <select className="field mt-2" value={settings.fragments} onChange={e=>setSettings({...settings,fragments:Number(e.target.value)})}>{[1,2,4,8,12,16].map(v=><option key={v} value={v}>{v} 條</option>)}</select>
        </label>
        <button className="btn-primary" onClick={saveSettings}>儲存設定</button>
        <div className="mt-8 border-t pt-5 text-sm text-slate-500">FFmpeg 狀態：<b className={health.ffmpeg?'text-emerald-600':'text-rose-600'}>{health.ffmpeg?'已安裝':'未偵測到'}</b></div>
        <p className="text-xs text-slate-400 mt-3">安全起見，服務預設只開放 127.0.0.1 本機連線。</p>
      </div>:<>
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 mb-8">
          {[[tasks.length,'全部任務',Download], [active,'下載 / 排隊',Activity], [completed,'已完成',CheckCircle2], [human(tasks.filter(t=>t.status==='completed').reduce((s,t)=>s+(t.size_bytes||0),0)),'完成大小',HardDrive]].map(([value,label,Icon])=><div key={label} className="card px-4 py-4 flex gap-3 items-center"><div className="bg-indigo-50 text-indigo-600 rounded-xl p-3"><Icon size={20}/></div><div className="min-w-0"><p className="text-xs text-slate-400">{label}</p><p className="text-xl font-extrabold truncate">{value}</p></div></div>)}
        </div>
        {page==='dashboard'&&<form onSubmit={create} className="card p-5 sm:p-7 mb-8">
          <h2 className="font-extrabold text-lg flex gap-2 items-center mb-1"><span className="p-2 bg-indigo-50 text-indigo-600 rounded-lg"><Plus size={18}/></span>新增下載任務</h2>
          <p className="text-sm text-slate-400 ml-10 mb-6">支援 YouTube 與其他 yt-dlp 相容網站</p>
          <label className="block font-semibold text-sm mb-2">影片網址</label>
          <div className="relative"><Link2 size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400"/><input type="url" required className="field !pl-12" placeholder="https://www.youtube.com/watch?v=…" value={url} onChange={e=>setUrl(e.target.value)}/></div>
          <div className="grid sm:grid-cols-2 gap-4 mt-5">
            <label className="text-sm font-semibold">影片畫質
              <select className="field mt-2" value={quality} onChange={e=>setQuality(e.target.value)}><option value="best">最佳畫質（推薦）</option>{[2160,1440,1080,720,480,360].map(v=><option key={v} value={v}>最高 {v}p</option>)}</select>
            </label>
            <label className="text-sm font-semibold">每段 MP4 大小
              <div className="relative mt-2"><input type="number" required min="10" max="50000" className="field !pr-14" value={splitMb} onChange={e=>setSplitMb(e.target.value)}/><span className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400">MB</span></div>
            </label>
          </div>
          <div className="border-t mt-6 pt-5 flex flex-wrap items-center justify-between gap-4">
            <label className="flex items-center gap-2 text-sm font-semibold cursor-pointer"><input type="checkbox" checked={autoSplit} onChange={e=>setAutoSplit(e.target.checked)} className="accent-indigo-600 w-4 h-4"/>下載完成後自動分割（各段可播放）</label>
            <button disabled={!connected||loading} className="btn-primary !py-3 !px-6">{loading?<LoaderCircle className="animate-spin" size={18}/>:<Download size={18}/>} 加入下載佇列</button>
          </div>
        </form>}
        <div className="flex flex-wrap gap-2 justify-between items-center mb-4"><h2 className="font-extrabold text-lg">下載任務 <span className="text-xs text-slate-500 bg-white rounded-full px-2 py-1 ml-1">{filtered.length}</span></h2>
        <div className="flex gap-1">{[['all','全部'],['active','進行中'],['completed','已完成'],['other','其他']].map(([k,v])=><button key={k} onClick={()=>setFilter(k)} className={'text-xs rounded-lg px-3 py-2 font-semibold '+(filter===k?'bg-indigo-600 text-white':'text-slate-500 hover:bg-white')}>{v}</button>)}</div></div>
        {filtered.length?<div className="space-y-4">{filtered.map(t=><Task key={t.id} item={t} act={action} notice={notice}/>)}</div>:<div className="card text-center py-20"><FileVideo size={34} className="text-indigo-300 mx-auto mb-4"/><h3 className="font-bold">目前沒有下載任務</h3><p className="text-sm text-slate-400 mt-2">貼上影片網址，開始第一個下載。</p></div>}
      </>}
    </main>
    {toast&&<div role="status" className={'fixed bottom-6 left-1/2 -translate-x-1/2 max-w-[90vw] rounded-xl px-5 py-3 shadow-xl text-sm font-semibold text-white '+(toast.error?'bg-rose-600':'bg-slate-900')}>{toast.message}</div>}
  </div>;
}
