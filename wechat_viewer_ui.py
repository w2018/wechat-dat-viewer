#!/usr/bin/env python
"""wechat_viewer_ui.py — Web 界面模板（桌面 / 手机两套 + 登录页）。

只放字符串与拼装函数，不含业务逻辑；主程序按 UA 选择渲染哪一套。
两套页面共用同一份 JS，只是 DOM 骨架与样式不同，元素 id 保持一致。
"""

from __future__ import annotations

# ------------------------------------------------------------------ 基础样式 ---

BASE_CSS = r"""
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--text:#1f2329;--sub:#6b7280;--accent:#2563eb;--danger:#dc2626}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:10px 20px}
h1{font-size:16px;margin:0 0 8px;font-weight:600}
.tabs{display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-right:12px}
.tabs button{border:0;border-radius:0;padding:6px 16px;background:#fff}
.tabs button.on{background:var(--accent);color:#fff}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px}
select,button,input{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--text)}
button{cursor:pointer}button:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
button:disabled{opacity:.45;cursor:not-allowed}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
button.danger{color:var(--danger);border-color:#f3c2c2}
.tag{color:var(--sub);font-size:12px}
.stat{font-weight:600;color:var(--accent)}
main{padding:14px 20px 40px}
.months{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.months button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.cell{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;position:relative;cursor:zoom-in}
.cell.sel{border-color:var(--accent);box-shadow:0 0 0 2px rgba(37,99,235,.18)}
.cell img{width:100%;height:140px;object-fit:cover;display:block;background:#eef0f3}
.cell .meta{padding:6px 8px;font-size:11px;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cell .chk{position:absolute;top:6px;left:6px;width:18px;height:18px;cursor:pointer;accent-color:var(--accent)}
.cell .play{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none}
.cell .play span{background:rgba(0,0,0,.55);color:#fff;border-radius:50%;width:34px;height:34px;display:flex;align-items:center;justify-content:center;font-size:14px}
.cell .info{display:none}
.more{display:block;margin:20px auto;padding:8px 24px}
.empty{color:var(--sub);padding:40px;text-align:center}
#tip{display:none;position:fixed;z-index:30;max-width:460px;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.16);padding:10px 12px;font-size:12px;line-height:1.7;pointer-events:none;word-break:break-all}
#tip b{color:var(--text)}#tip .k{color:var(--sub);display:inline-block;min-width:64px}
#tipmask{display:none}
#box{display:none;position:fixed;inset:0;background:rgba(15,20,30,.92);z-index:20;align-items:center;justify-content:center;flex-direction:column}
#box.on{display:flex}#box img,#box video{max-width:94vw;max-height:84vh;object-fit:contain;background:#000}
#box .cap{color:#dbe2ea;margin-top:10px;font-size:12px}
#box .close{position:absolute;top:16px;right:20px;color:#fff;background:none;border:1px solid #6b7280;font-size:16px;padding:4px 12px}
#box .nav{display:none}
#modal{display:none;position:fixed;inset:0;background:rgba(15,20,30,.6);z-index:40;align-items:center;justify-content:center;padding:20px}
#modal.on{display:flex}
.dialog{background:#fff;border-radius:10px;width:min(760px,96vw);max-height:88vh;display:flex;flex-direction:column;overflow:hidden}
.dialog h2{font-size:16px;margin:0;padding:14px 18px;border-bottom:1px solid var(--line)}
.dialog .body{padding:14px 18px;overflow:auto}
.dialog .foot{padding:12px 18px;border-top:1px solid var(--line);display:flex;gap:10px;justify-content:flex-end;align-items:center}
.warn{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;padding:10px 12px;border-radius:6px;font-weight:700;margin-bottom:12px}
.list{background:#f8f9fb;border:1px solid var(--line);border-radius:6px;max-height:220px;overflow:auto;padding:8px;font-family:Consolas,monospace;font-size:11px;line-height:1.6}
.result{white-space:pre-wrap;font-size:13px}
.scaninfo{display:flex;align-items:center;gap:10px;flex:1;min-width:280px}
.track{flex:1;height:8px;background:#e9edf2;border-radius:5px;overflow:hidden;max-width:420px}
#scanfill{height:100%;width:0;background:var(--accent);transition:width .25s}
#scantext{font-size:12px;color:var(--sub);white-space:nowrap}
#scantext.done{color:#16a34a}#scantext.err{color:var(--danger)}
"""

# ------------------------------------------------------------------ 桌面骨架 ---

DESKTOP_HTML = r"""
<header>
<h1>微信图片 / 视频查看器 <span class="tag" id="keyinfo"></span></h1>
<div class="bar">
  <div class="tabs"><button id="tab-image" class="on">图片分区</button><button id="tab-video">视频分区</button></div>
  <span class="tag" id="mode"></span>
  <button id="btn-logout" style="margin-left:auto">退出登录</button>
</div>
<div class="bar" id="scanbar">
  <button id="btn-rescan">重新扫描</button>
  <div class="scaninfo"><span id="scantext">准备就绪</span><div class="track"><div id="scanfill"></div></div></div>
</div>
<div class="bar" id="bar-image"><span class="tag">会话</span><select id="sid" style="min-width:400px"></select></div>
<div class="bar"><div class="months" id="months"></div></div>
<div class="bar">
  <label class="tag"><input type="checkbox" id="selall"> 全选本页</label>
  <span class="stat" id="selstat">已选 0 项 · 0 MB</span>
  <button id="btn-export" class="primary">导出勾选</button>
  <button id="btn-delete" class="danger">删除勾选（移入回收站）</button>
  <span class="tag" id="stat"></span>
</div>
</header>
<main><div class="grid" id="grid"></div><button class="more" id="more" style="display:none">加载更多</button><div class="empty" id="empty">正在加载…</div></main>
"""

# ------------------------------------------------------------------ 手机骨架 ---

MOBILE_HTML = r"""
<header>
  <div class="mhead">
    <div class="mtitle">微信图片 / 视频 <span class="tag" id="keyinfo"></span></div>
    <button id="btn-menu" class="iconbtn" aria-label="筛选">☰</button>
  </div>
  <div class="mline">
    <div class="tabs"><button id="tab-image" class="on">图片分区</button><button id="tab-video">视频分区</button></div>
    <span class="tag" id="mode"></span>
  </div>
  <div class="panel open" id="panel">
    <div class="bar" id="scanbar">
      <div class="scaninfo"><span id="scantext">准备就绪</span><div class="track"><div id="scanfill"></div></div></div>
      <button id="btn-rescan">重新扫描</button>
    </div>
    <div class="bar" id="bar-image"><span class="tag">会话</span><select id="sid"></select></div>
    <div class="months" id="months"></div>
    <div class="bar"><label class="tag"><input type="checkbox" id="selall"> 全选本页</label><span class="tag" id="stat"></span></div>
  </div>
</header>
<main><div class="grid" id="grid"></div><button class="more" id="more" style="display:none">加载更多</button><div class="empty" id="empty">正在加载…</div></main>
<div class="mbar">
  <span class="stat" id="selstat">已选 0 项 · 0 MB</span>
  <button id="btn-export" class="primary">导出</button>
  <button id="btn-delete" class="danger">删除</button>
  <button id="btn-logout">退出</button>
</div>
"""

# ------------------------------------------------------------------ 公共尾部 ---

TAIL_HTML = r"""
<div id="tipmask"></div>
<div id="tip"></div>
<div id="box">
  <button class="close" onclick="closeBox()">关闭 ×</button>
  <img id="big" style="display:none"><video id="vid" controls playsinline webkit-playsinline style="display:none" onerror="videoError()"></video>
  <div class="cap" id="cap"></div>
  <button class="nav prev" onclick="hop(-1)">‹</button>
  <button class="nav next" onclick="hop(1)">›</button>
</div>
<div id="modal"><div class="dialog"><h2 id="mtitle">确认操作</h2><div class="body" id="mbody"></div><div class="foot" id="mfoot"></div></div></div>
"""

# ------------------------------------------------------------------ 手机样式 ---

MOBILE_CSS = r"""
html{-webkit-text-size-adjust:100%}
body{padding-bottom:calc(58px + env(safe-area-inset-bottom));font-size:15px}
header{padding:8px 12px}
.mhead{display:flex;align-items:center;justify-content:space-between;gap:8px}
.mtitle{font-size:15px;font-weight:600}
.mtitle .tag{display:block;font-size:10px;margin-top:2px;font-weight:400}
.mline{display:flex;align-items:center;gap:10px;margin-top:8px;flex-wrap:wrap}
.tabs{margin-right:0}
.tabs button{padding:7px 14px}
.iconbtn{padding:4px 10px;font-size:16px;line-height:1}
.panel{display:none;margin-top:8px}
.panel.open{display:block}
.bar{gap:8px}
select{width:100%;min-width:0!important;padding:9px 10px}
body .bar select{margin-top:2px}
.months{overflow-x:auto;flex-wrap:nowrap;margin:8px 0 2px;padding-bottom:4px;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.months::-webkit-scrollbar{display:none}
.months button{flex:0 0 auto;padding:6px 12px}
main{padding:10px 10px 20px}
.grid{grid-template-columns:repeat(2,1fr);gap:8px}
.cell{cursor:pointer}
.cell img{height:38vw;max-height:190px}
.cell .meta{font-size:10px;padding:5px 6px}
.cell .chk{width:24px;height:24px;top:4px;left:4px}
.cell .info{display:block;position:absolute;top:4px;right:4px;width:24px;height:24px;padding:0;border-radius:50%;
  background:rgba(0,0,0,.5);color:#fff;border:0;font-size:12px;line-height:24px;text-align:center}
.empty{padding:28px 10px}
.more{width:100%;padding:10px;margin:14px 0}
.mbar{position:fixed;left:0;right:0;bottom:0;z-index:12;display:flex;gap:8px;align-items:center;
  padding:8px 12px calc(8px + env(safe-area-inset-bottom));background:var(--card);border-top:1px solid var(--line)}
.mbar .stat{flex:1;font-size:12px;line-height:1.3}
.mbar button{padding:8px 12px;font-size:13px}
#tip{display:block;visibility:hidden;left:0!important;right:0;top:auto!important;bottom:0;max-width:none;
  border-radius:14px 14px 0 0;padding:14px 16px calc(16px + env(safe-area-inset-bottom));font-size:13px;
  pointer-events:auto;transform:translateY(102%);transition:transform .22s ease;box-shadow:0 -8px 28px rgba(0,0,0,.18);
  max-height:70vh;overflow:auto;z-index:36}
#tip.on{transform:none;visibility:visible}
#tipmask{position:fixed;inset:0;background:rgba(15,20,30,.35);z-index:35;display:none}
#tipmask.on{display:block}
#tip .k{min-width:72px}
#box{background:#0b0f14}
#box img,#box video{max-width:100vw;max-height:100vh;width:auto}
#box .cap{position:absolute;bottom:calc(14px + env(safe-area-inset-bottom));font-size:11px;max-width:92vw;text-align:center;word-break:break-all}
#box .close{top:calc(10px + env(safe-area-inset-top));right:12px;font-size:13px;padding:6px 10px;background:rgba(0,0,0,.45)}
#box .nav{display:flex;position:absolute;top:50%;transform:translateY(-50%);width:40px;height:64px;align-items:center;justify-content:center;
  background:rgba(0,0,0,.35);color:#fff;border:0;font-size:24px;line-height:1;padding:0}
#box .nav.prev{left:0;border-radius:0 8px 8px 0}#box .nav.next{right:0;border-radius:8px 0 0 8px}
#modal{padding:0;align-items:flex-end}
.dialog{width:100%;max-height:92vh;border-radius:14px 14px 0 0}
.dialog .body{padding:12px 14px}
.dialog .foot{padding:10px 14px calc(12px + env(safe-area-inset-bottom));flex-wrap:wrap}
.dialog .foot button{flex:1;min-width:120px;padding:10px}
.list{max-height:34vh}
#cword{width:100%!important}
input[type=checkbox]{width:20px;height:20px}
"""

# ------------------------------------------------------------------ 公共 JS ---

APP_JS = r"""
const MOBILE=__MOBILE_FLAG__;
let ZONE='image',SID='',MONTH='',OFFSET=0,LIMIT=MOBILE?60:120,TOTAL=0,ALLOW=false,PENDING=null,CUR=-1;
const SEL=new Set(), INFO={};
let ITEMS=[];
const $=id=>document.getElementById(id);
function fmt(n){return n>=1073741824?(n/1073741824).toFixed(2)+' GB':n>=1048576?(n/1048576).toFixed(1)+' MB':(n/1024).toFixed(0)+' KB'}
async function api(u,opt){
  const r=await fetch(u,opt);
  if(r.status===401){location.href='/wx';throw new Error('登录已失效')}
  if(!r.ok)throw new Error((await r.text()).slice(0,300));
  return r.json();
}
function post(u,obj){return api(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(obj)})}
function stub(){return{zone:ZONE,sid:SID,month:MONTH,bases:[...SEL]}}
function updateStat(){
  let n=0,s=0;for(const b of SEL){const it=ITEMS.find(x=>x.base===b);if(it){n++;s+=it.size}}
  $('selstat').textContent=`已选 ${n} 项 · ${fmt(s)}`;
  $('btn-export').disabled=n===0;$('btn-delete').disabled=n===0||!ALLOW;
}
async function init(){
  const k=await api('/api/status');ALLOW=k.allow_delete;
  $('keyinfo').textContent='密钥 '+k.key_desc;
  $('mode').textContent=ALLOW?(MOBILE?'可删除':'删除已启用（移入回收站）'):'只读模式';
  $('sid').onchange=()=>{SID=$('sid').value;showMonths()};
  $('tab-image').onclick=()=>switchZone('image');$('tab-video').onclick=()=>switchZone('video');
  $('btn-rescan').onclick=()=>startScan();
  if($('btn-logout'))$('btn-logout').onclick=logout;
  if($('btn-menu'))$('btn-menu').onclick=()=>$('panel').classList.toggle('open');
  $('more').onclick=()=>load(false);
  $('selall').onchange=e=>{
    [...$('grid').children].forEach(c=>{const b=c.dataset.base;if(e.target.checked)SEL.add(b);else SEL.delete(b);c.classList.toggle('sel',e.target.checked);c.querySelector('.chk').checked=e.target.checked});updateStat();
  };
  await startScan();
}
async function logout(){
  try{await fetch('/api/auth/logout',{method:'POST'})}catch(e){}
  location.href='/wx';
}
async function startScan(){
  $('btn-rescan').disabled=true;
  try{
    const r=await post('/api/rescan',{});
    if(!r.started){$('scantext').textContent=r.message||'扫描进行中…'}
    await pollScan();
  }catch(e){
    $('scantext').textContent='启动扫描失败：'+e.message;
    $('scantext').className='err';$('btn-rescan').disabled=false;
  }
}
async function pollScan(){
  const s=await api('/api/rescan/status');
  const pct=s.total?Math.round(s.done/s.total*100):(s.finished?100:0);
  $('scanfill').style.width=pct+'%';
  $('scantext').textContent=s.message+(s.elapsed?` · ${s.elapsed}s`:'');
  $('scantext').className=s.error?'err':(s.finished&&!s.running?'done':'');
  if(s.running){setTimeout(pollScan,300);return}
  $('btn-rescan').disabled=false;
  if(s.error)return;
  const ss=await api('/api/sessions');
  const keep=SID;
  $('sid').innerHTML=ss.map(s=>`<option value="${s.sid}">${s.first_date||'—'} → ${s.last_date||'—'} · ${fmt(s.size_bytes||s.size_mb*1048576)} · ${s.file_count} 文件 · ${s.sid.slice(0,10)}…</option>`).join('');
  if(ss.length){SID=(keep&&ss.some(x=>x.sid===keep))?keep:ss[0].sid;$('sid').value=SID}
  await showMonths();
}
function switchZone(z){
  ZONE=z;$('tab-image').classList.toggle('on',z==='image');$('tab-video').classList.toggle('on',z==='video');
  $('bar-image').style.display=z==='image'?'flex':'none';
  SEL.clear();ITEMS=[];showMonths();
}
async function showMonths(){
  const ms=ZONE==='image'?(SID?await api('/api/months?sid='+SID):[]):await api('/api/video_months');
  $('months').innerHTML=ms.map(m=>`<button data-m="${m}">${m}</button>`).join('');
  [...$('months').children].forEach(b=>b.onclick=()=>{MONTH=b.dataset.m;[...$('months').children].forEach(x=>x.classList.remove('on'));b.classList.add('on');load(true)});
  if(ms.length){MONTH=ms[ms.length-1];$('months').lastChild.classList.add('on');load(true)}else{reset('该分区没有内容')}
}
function reset(msg){$('grid').innerHTML='';ITEMS=[];$('more').style.display='none';$('empty').textContent=msg;$('empty').style.display='block';$('stat').textContent='';SEL.clear();updateStat()}
async function load(fresh){
  if(fresh){OFFSET=0;$('grid').innerHTML='';ITEMS=[];SEL.clear()}
  const u=ZONE==='image'?`/api/images?sid=${SID}&month=${MONTH}&offset=${OFFSET}&limit=${LIMIT}`:`/api/videos?month=${MONTH}&offset=${OFFSET}&limit=${LIMIT}`;
  const d=await api(u);TOTAL=d.total;ITEMS=ITEMS.concat(d.items);
  $('empty').style.display=TOTAL?'none':'block';
  if(!TOTAL){reset('该月份没有内容');return}
  d.items.forEach(it=>{
    const c=document.createElement('div');c.className='cell';c.dataset.base=it.base;
    const src=ZONE==='image'?`/api/img?sid=${SID}&month=${MONTH}&base=${encodeURIComponent(it.base)}&kind=thumb`:`/api/video_thumb?month=${MONTH}&base=${encodeURIComponent(it.base)}`;
    c.innerHTML=`<input type="checkbox" class="chk" ${SEL.has(it.base)?'checked':''}><img loading="lazy" src="${src}" alt=""><div class="meta">${it.base.slice(0,10)} · ${fmt(it.size)}${it.has_hd?' · 原图':''}</div>${ZONE==='video'?'<div class="play"><span>▶</span></div>':''}${MOBILE?'<button class="info" aria-label="详情">i</button>':''}`;
    c.querySelector('.chk').onclick=e=>{e.stopPropagation();if(e.target.checked)SEL.add(it.base);else SEL.delete(it.base);c.classList.toggle('sel',e.target.checked);updateStat()};
    c.onclick=()=>openBox(it);
    if(MOBILE){
      c.querySelector('.info').onclick=e=>{e.stopPropagation();showTip(it.base)};
    }else{
      c.onmouseenter=e=>showTip(it.base,e);c.onmousemove=moveTip;c.onmouseleave=hideTip;
    }
    $('grid').appendChild(c);
  });
  OFFSET+=d.items.length;
  $('stat').textContent=`${MONTH} · 共 ${TOTAL} 项 · 已显示 ${OFFSET} 项`;
  $('more').style.display=OFFSET<TOTAL?'block':'none';
  $('selall').checked=false;updateStat();
}
function tipHtml(m){
  const dim=m.width?`${m.width} × ${m.height}`:'未知';
  const dur=m.duration?`${m.duration} 秒`:'—';
  const rows=m.files.map(f=>`<div><span class="k">路径</span><b>${f.path}</b><br><span class="k">日期时间</span>${f.mtime_str}　<span class="k">大小</span>${fmt(f.size)}${f.nlink>1?'　<span style="color:#dc2626">硬链接 '+f.nlink+'</span>':''}</div>`).join('<hr style="border:0;border-top:1px solid #eee">');
  return `<div><span class="k">分区</span><b>${ZONE==='image'?'图片':'视频'}</b>　<span class="k">格式</span><b>${m.format}</b></div><div><span class="k">像素尺寸</span><b>${dim}</b>　<span class="k">时长</span>${dur}　<span class="k">合计</span>${fmt(m.total_size)}</div><hr style="border:0;border-top:1px solid #eee">${rows}`;
}
async function showTip(base,e){
  const key=ZONE+'|'+SID+'|'+MONTH+'|'+base;
  let m=INFO[key];
  if(!m){
    m=await api(`/api/info?zone=${ZONE}&sid=${SID}&month=${MONTH}&base=${encodeURIComponent(base)}`);INFO[key]=m;
  }
  $('tip').innerHTML=tipHtml(m)+(MOBILE?'<div style="margin-top:10px;color:#6b7280;font-size:12px">点击空白处关闭</div>':'');
  if(MOBILE){$('tip').classList.add('on');$('tipmask').classList.add('on')}
  else{$('tip').style.display='block';moveTip(e)}
}
function moveTip(e){const t=$('tip');const x=Math.min(e.clientX+16,innerWidth-480),y=Math.min(e.clientY+16,innerHeight-260);t.style.left=Math.max(8,x)+'px';t.style.top=Math.max(8,y)+'px'}
function hideTip(){
  $('tip').classList.remove('on');$('tipmask').classList.remove('on');
  if(!MOBILE)$('tip').style.display='none';
}
function renderBox(it){
  if(ZONE==='image'){
    $('vid').style.display='none';$('vid').pause();$('big').style.display='block';
    $('big').src=`/api/img?sid=${SID}&month=${MONTH}&base=${encodeURIComponent(it.base)}&kind=full`;
  }else{
    $('big').style.display='none';$('vid').style.display='block';
    $('vid').src=`/api/video_stream?month=${MONTH}&base=${encodeURIComponent(it.base)}`;$('vid').play().catch(()=>{});
  }
  $('cap').textContent=`${it.base} · ${fmt(it.size)}${TOTAL?` · ${CUR+1}/${ITEMS.length}`:''}`;
}
function openBox(it){
  CUR=ITEMS.findIndex(x=>x.base===it.base);
  $('box').classList.add('on');
  renderBox(it);
}
function hop(d){
  if(CUR<0)return;
  const n=CUR+d;
  if(n<0||n>=ITEMS.length)return;
  CUR=n;renderBox(ITEMS[n]);
}
function closeBox(){$('box').classList.remove('on');$('big').src='';$('vid').pause();$('vid').src=''}
function videoError(){
  if(!$('box').classList.contains('on'))return;
  $('vid').style.display='none';$('big').style.display='block';
  $('big').src='/api/placeholder?text='+encodeURIComponent('不支持播放，需要解码器');
  $('cap').textContent='不支持播放，需要解码器';
}
function modal(title,body,foot){$('mtitle').textContent=title;$('mbody').innerHTML=body;$('mfoot').innerHTML='';foot.forEach(h=>{$('mfoot').appendChild(h)});$('modal').classList.add('on')}
function closeModal(){$('modal').classList.remove('on');PENDING=null}
function btn(text,cls,fn){const b=document.createElement('button');b.textContent=text;b.className=cls||'';b.onclick=fn;return b}
$('btn-export').onclick=async()=>{
  if(!SEL.size)return;
  try{
    const r=await post('/api/export',stub());
    modal('导出完成',`<div class="result">已导出 ${r.count} 个文件\nZIP：${r.path}\n大小：${fmt(r.bytes)}</div>`,[btn('下载 ZIP','primary',()=>location.href='/api/download?name='+encodeURIComponent(r.name)),btn('关闭','',closeModal)]);
  }catch(e){modal('导出失败',`<div class="result">${e.message}</div>`,[btn('关闭','',closeModal)])}
};
$('btn-delete').onclick=async()=>{
  if(!SEL.size||!ALLOW)return;
  try{
    const p=await post('/api/delete/preview',stub());PENDING=p.token;
    const list=p.files.map(f=>`${f.path}　(${fmt(f.size)})`).join('<br>');
    const body=`<div class="warn">⚠️ ${p.warning}</div>
      <div class="result">分组 <b>${p.group_count}</b> 项，实际文件 <b>${p.file_count}</b> 个，合计 <b>${fmt(p.total_size)}</b>${p.hardlinked_files?`<br><span style="color:#dc2626">其中 ${p.hardlinked_files} 个是硬链接文件，删除后不一定立刻释放空间</span>`:''}</div>
      <div class="list" style="margin:10px 0">${list}</div>
      <div>请输入 <b>${p.confirm_word}</b> 完成二次确认：<br><input id="cword" style="width:320px;margin-top:6px" autocomplete="off" placeholder="手工输入确认词"></div>`;
    modal('删除前确认（第一步：清单与风险）',body,[
      btn('取消','',closeModal),
      btn('第二步：移入回收站','danger',async()=>{
        const w=$('cword').value.trim();
        if(w!==p.confirm_word){alert('确认词不正确，未执行任何删除');return}
        try{
          const r=await post('/api/delete/commit',{token:p.token,confirm:w});
          load(true);
          modal('删除结果',`<div class="result">已移入回收站：${r.deleted} 个文件（${r.batches} 批）\n失败：${r.failed} 个${r.stopped_early?'\n已中止剩余批次':''}\n日志：${r.log}\n\n可从系统回收站还原。</div>`,[btn('关闭','',closeModal)]);
        }catch(e){modal('删除失败',`<div class="result">${e.message}</div>`,[btn('关闭','',closeModal)])}
      })
    ]);
  }catch(e){modal('无法预览删除',`<div class="result">${e.message}</div>`,[btn('关闭','',closeModal)])}
};
$('box').onclick=e=>{if(e.target.id==='box')closeBox()};
$('tipmask').onclick=hideTip;
document.onkeydown=e=>{if(e.key==='Escape'){closeBox();closeModal();hideTip()}};
if(MOBILE){
  let tx=0,ty=0;
  $('box').addEventListener('touchstart',e=>{tx=e.touches[0].clientX;ty=e.touches[0].clientY},{passive:true});
  $('box').addEventListener('touchend',e=>{
    if(!$('box').classList.contains('on'))return;
    const dx=e.changedTouches[0].clientX-tx,dy=e.changedTouches[0].clientY-ty;
    if(Math.abs(dx)>50&&Math.abs(dx)>Math.abs(dy))hop(dx<0?1:-1);
  },{passive:true});
}
init().catch(e=>reset('加载失败：'+e.message));
"""

# ------------------------------------------------------------------ 拼装 ---

PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<title>微信图片 / 视频查看器</title>
<style>__CSS__</style></head><body class="__BODYCLASS__">
__BODY__<script>__JS__</script></body></html>"""


def build_page(mobile: bool) -> str:
    css = BASE_CSS + (MOBILE_CSS if mobile else "")
    return (PAGE_TEMPLATE
            .replace("__CSS__", css)
            .replace("__BODYCLASS__", "m" if mobile else "")
            .replace("__BODY__", (MOBILE_HTML if mobile else DESKTOP_HTML) + TAIL_HTML)
            .replace("__JS__", APP_JS.replace("__MOBILE_FLAG__", "true" if mobile else "false")))


AUTH_CSS = r"""
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#f6f7f9;
  color:#1f2329;font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;padding:20px}
.card{width:100%;max-width:380px;background:#fff;border:1px solid #e3e6ea;border-radius:12px;padding:26px 24px;
  box-shadow:0 10px 34px rgba(17,24,39,.07)}
h1{font-size:17px;margin:0 0 6px;font-weight:600}
p.sub{margin:0 0 18px;color:#6b7280;font-size:12.5px;line-height:1.6}
label{display:block;font-size:12.5px;color:#6b7280;margin:12px 0 6px}
input{width:100%;font:inherit;padding:11px 12px;border:1px solid #e3e6ea;border-radius:8px;background:#fff;color:#1f2329}
input:focus{outline:0;border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.12)}
button{width:100%;margin-top:18px;padding:11px;border:0;border-radius:8px;background:#2563eb;color:#fff;font:inherit;cursor:pointer}
button:disabled{opacity:.5;cursor:not-allowed}
.msg{margin-top:12px;font-size:12.5px;color:#dc2626;min-height:18px;line-height:1.5}
.hint{margin-top:16px;font-size:11.5px;color:#9aa3ad;line-height:1.7}
.pwline{display:flex;gap:8px;align-items:center}
.pwline .toggle{width:auto;margin:0;padding:0 10px;background:#fff;color:#6b7280;border:1px solid #e3e6ea;border-radius:8px;font-size:12px}
@media (max-width:520px){
  body{padding:0;align-items:stretch}
  .card{max-width:none;min-height:100vh;border:0;border-radius:0;padding:32px 22px;box-shadow:none;display:flex;flex-direction:column;justify-content:center}
  input,button{padding:13px 12px;font-size:16px}
}
"""

AUTH_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<title>__TITLE__</title>
<style>__CSS__</style></head><body>
<div class="card">
  <h1>__TITLE__</h1>
  <p class="sub">__SUB__</p>
  <form id="f" autocomplete="off">
    <label>密码</label>
    <div class="pwline"><input id="pw" type="password" autocomplete="current-password" placeholder="请输入密码"><button class="toggle" type="button" id="eye">显示</button></div>
    __CONFIRM__
    <button id="go" type="submit">__ACTION__</button>
  </form>
  <div class="msg" id="msg"></div>
  <div class="hint">__HINT__</div>
</div>
<script>
const MODE=__MODE__,BAN=__BAN__;
const $=id=>document.getElementById(id);
$('eye').onclick=()=>{const p=$('pw');const on=p.type==='password';p.type=on?'text':'password';$('eye').textContent=on?'隐藏':'显示'};
if(BAN>0){
  $('go').disabled=true;$('pw').disabled=true;
  let left=BAN;
  const tick=()=>{
    if(left<=0){$('msg').textContent='';$('go').disabled=false;$('pw').disabled=false;return}
    const m=Math.floor(left/60),s=left%60;
    $('msg').textContent=`尝试次数过多，请在 ${m}:${String(s).padStart(2,'0')} 后重试`;
    left--;setTimeout(tick,1000);
  };tick();
}
$('f').onsubmit=async e=>{
  e.preventDefault();
  const pw=$('pw').value;
  if(MODE==='setup'){
    if(pw.length<6){$('msg').textContent='密码至少 6 位';return}
    if(pw!==$('pw2').value){$('msg').textContent='两次输入的密码不一致';return}
  }
  $('go').disabled=true;$('msg').textContent='';
  try{
    const r=await fetch(MODE==='setup'?'/api/auth/setup':'/api/auth/login',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password:pw,confirm:$('pw2')?$('pw2').value:''})
    });
    const d=await r.json().catch(()=>({}));
    if(r.ok){location.href='/wx';return}
    $('msg').textContent=d.error||('操作失败（'+r.status+'）');
    if(d.retry_after){setTimeout(()=>location.reload(),600)}
    $('go').disabled=false;
  }catch(err){$('msg').textContent='网络错误：'+err.message;$('go').disabled=false}
};
</script></body></html>"""


def auth_page(mobile: bool, setup: bool, ban_left: int = 0, local: bool = True) -> str:
    if setup:
        title = "首次使用：设置访问密码"
        sub = "为这台查看器设置一个访问密码，至少 6 位。密码只保存在本机程序目录，不会上传。"
        confirm = '<label>再输一次</label><input id="pw2" type="password" autocomplete="new-password" placeholder="再次输入密码">'
        action = "设置并进入"
        hint = "忘记密码时，删除程序目录下的 wechat_viewer_key.json 后重启即可重新设置。"
        if not local:
            hint = "首次设置密码请在运行程序的电脑上打开 127.0.0.1 的 /wx 入口完成。"
    else:
        title = "微信图片 / 视频查看器"
        sub = "请输入访问密码。"
        confirm = ""
        action = "登录"
        hint = "连续输错 3 次（30 秒内）将禁止该 IP 访问 10 分钟。"
    html = (AUTH_TEMPLATE
            .replace("__CSS__", AUTH_CSS)
            .replace("__TITLE__", title)
            .replace("__SUB__", sub)
            .replace("__CONFIRM__", confirm)
            .replace("__ACTION__", action)
            .replace("__HINT__", hint)
            .replace("__MODE__", "'setup'" if setup else "'login'")
            .replace("__BAN__", str(max(0, int(ban_left))))
            )
    if not local:
        html = html.replace("<button id=\"go\"", "<button id=\"go\" disabled")
    return html
