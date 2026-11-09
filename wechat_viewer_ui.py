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
#grid{display:block}
.daysec{margin:0 0 18px}
.dayhead{display:flex;align-items:center;gap:10px;padding:7px 10px;margin:0 0 8px;background:#eef2f7;border:1px solid var(--line);border-radius:7px}
.dayhead .dall{display:flex;align-items:center;gap:7px;font-weight:700;font-size:13px;cursor:pointer;font-family:Consolas,monospace}
.dayhead .dall input{margin:0;width:15px;height:15px}
.dayhead .dstat{margin-left:auto;color:var(--sub);font-size:12px;white-space:nowrap}
.dgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.cell{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;position:relative;cursor:pointer}
.cell.sel{border-color:var(--accent);box-shadow:0 0 0 2px rgba(37,99,235,.18)}
#box #big{transition:transform .12s ease-out;touch-action:none;user-select:none;-webkit-user-drag:none}
.cell img{width:100%;height:140px;object-fit:cover;display:block;background:#eef0f3}
.cell .meta{display:flex;align-items:center;gap:6px;padding:6px 8px;font-size:11px;color:var(--sub);overflow:hidden}
.cell .meta .name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cell .meta .kt{flex:none;font-size:10.5px;font-weight:700;letter-spacing:.2px}
.cell .meta .kt-hd{color:#dc2626}
.cell .meta .kt-main{color:#2563eb}
.cell .meta .kt-thumb{color:#8b929c}
.cell .meta .kt-video{color:#7c3aed}
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
#boxsel{display:none;position:fixed;z-index:38;border:1px solid #2563eb;background:rgba(37,99,235,.12);border-radius:2px;pointer-events:none}
body.bxing{user-select:none;-webkit-user-select:none;cursor:crosshair}
body.bxing .cell{cursor:crosshair}
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
.kinds{display:flex;gap:6px;align-items:center;flex:none}
.kchip{display:flex;align-items:center;gap:5px;padding:5px 9px;border:1px solid var(--line);border-radius:6px;background:#fff;font-size:12.5px;color:var(--sub);cursor:pointer;user-select:none;font-weight:600}
.kchip input{margin:0;width:13px;height:13px;cursor:pointer;accent-color:var(--accent)}
.kchip:has(input:checked){border-color:var(--accent);background:#eff6ff;color:var(--accent)}
.autoload{display:flex;align-items:center;justify-content:center;gap:8px;padding:14px 0;color:var(--sub);font-size:12.5px}
.spin{width:15px;height:15px;border:2px solid #d6dbe3;border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;flex:none}
@keyframes spin{to{transform:rotate(360deg)}}
.sentinel{height:1px}
.krow{display:flex;align-items:center;gap:10px;padding:8px 10px;border:1px solid var(--line);border-radius:6px;margin-bottom:8px;cursor:pointer;user-select:none}
.krow:hover{border-color:#c7cdd6}
.krow.on{border-color:#fca5a5;background:#fff7f7}
.krow input{width:16px;height:16px;flex:none;margin:0;accent-color:var(--danger)}
.krow .ktxt{display:flex;flex-direction:column;line-height:1.4;min-width:0}
.krow .klabel{font-weight:600;font-size:13px}
.krow .kdesc{color:var(--sub);font-size:12px}
.krow .kstat{margin-left:auto;color:var(--sub);font-size:12px;white-space:nowrap;padding-left:8px}
.dprog{display:flex;flex-direction:column;gap:10px}
.dprog .track{max-width:none;height:10px;background:#e9edf2}
.dprog #dfill{height:100%;width:0;background:linear-gradient(90deg,#dc2626,#f97316);transition:width .2s}
.dprog .num{font-size:13px}
.dprog .num b{color:var(--danger)}
.dprog .cur{color:var(--sub);font-size:11px;font-family:Consolas,monospace;word-break:break-all;line-height:1.5}
.llist{max-height:52vh;overflow:auto;border:1px solid var(--line);border-radius:8px}
.lrow{padding:8px 10px;border-bottom:1px solid var(--line);font-size:12px}
.lrow:last-child{border-bottom:0}
.lrow.bad{background:#fff7f7}
.lhead{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.ltime{font-family:Consolas,monospace;color:var(--sub)}
.lip{color:var(--accent);font-family:Consolas,monospace}
.ltag{background:#eef2f7;border-radius:4px;padding:1px 6px;font-weight:600}
.lrow.bad .ltag{background:#fee2e2;color:#b91c1c}
.ldetail{margin-top:3px;line-height:1.5;word-break:break-all}
.lfiles{margin-top:2px;color:var(--sub);font-family:Consolas,monospace;font-size:11px;word-break:break-all}
.lbar{margin-bottom:8px;color:var(--sub);font-size:12px}
.lbar b{color:var(--text)}
"""

# ------------------------------------------------------------------ 桌面骨架 ---

DESKTOP_HTML = r"""
<header>
<h1>微信图片 / 视频查看器 <span class="tag" id="keyinfo"></span></h1>
<div class="bar">
  <div class="tabs"><button id="tab-image" class="on">图片分区</button><button id="tab-video">视频分区</button></div>
  <span class="tag" id="mode"></span>
  <button id="btn-logs" style="margin-left:auto">操作日志</button>
  <button id="btn-logout">退出登录</button>
</div>
<div class="bar" id="scanbar">
  <button id="btn-rescan">重新扫描</button>
  <div class="scaninfo"><span id="scantext">准备就绪</span><div class="track"><div id="scanfill"></div></div></div>
</div>
<div class="bar" id="bar-image">
  <span class="tag">会话</span><select id="sid" style="min-width:280px;max-width:520px"></select>
  <span class="tag">类型</span>
  <div class="kinds" id="kindfilter" title="可多选，勾中的类型都会显示">
    <label class="kchip"><input type="checkbox" value="hd" checked><span>原图</span></label>
    <label class="kchip"><input type="checkbox" value="main" checked><span>普通图</span></label>
    <label class="kchip"><input type="checkbox" value="thumb" checked><span>缩略图</span></label>
  </div>
</div>
<div class="bar"><div class="months" id="months"></div></div>
<div class="bar">
  <label class="tag"><input type="checkbox" id="selall"> 全选本页</label>
  <span class="stat" id="selstat">已选 0 项 · 0 MB</span>
  <button id="btn-export" class="primary">导出勾选</button>
  <button id="btn-delete" class="danger">删除勾选（移入回收站）</button>
  <span class="tag" id="stat"></span>
</div>
</header>
<main><div class="grid" id="grid"></div><div class="autoload" id="autoload" style="display:none"><span class="spin"></span><span>正在加载…</span></div><div class="sentinel" id="sentinel"></div><div class="empty" id="empty">正在加载…</div></main>
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
    <div class="bar" id="bar-image">
      <span class="tag">会话</span><select id="sid"></select>
      <div class="kinds" id="kindfilter" title="可多选">
        <label class="kchip"><input type="checkbox" value="hd" checked><span>原图</span></label>
        <label class="kchip"><input type="checkbox" value="main" checked><span>普通</span></label>
        <label class="kchip"><input type="checkbox" value="thumb" checked><span>缩略</span></label>
      </div>
    </div>
    <div class="months" id="months"></div>
    <div class="bar"><label class="tag"><input type="checkbox" id="selall"> 全选本页</label><span class="tag" id="stat"></span></div>
  </div>
</header>
<main><div class="grid" id="grid"></div><div class="autoload" id="autoload" style="display:none"><span class="spin"></span><span>正在加载…</span></div><div class="sentinel" id="sentinel"></div><div class="empty" id="empty">正在加载…</div></main>
<div class="mbar">
  <span class="stat" id="selstat">已选 0 项 · 0 MB</span>
  <button id="btn-export" class="primary">导出</button>
  <button id="btn-delete" class="danger">删除</button>
  <button id="btn-logs">日志</button>
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
  .dgrid{grid-template-columns:repeat(2,1fr);gap:8px}
  .dayhead{padding:6px 8px;margin-bottom:6px}
  .dayhead .dall{font-size:12px}
  .dayhead .dstat{font-size:11px}
  .daysec{margin-bottom:12px}
  .kinds{gap:4px}
  .kchip{padding:4px 7px;font-size:11.5px}
  .autoload{padding:10px 0;font-size:12px}
.cell{cursor:pointer}
.cell img{height:38vw;max-height:190px}
.cell .meta{font-size:10px;padding:5px 6px}
  .cell .meta .kt{font-size:9.5px}
.cell .chk{width:24px;height:24px;top:4px;left:4px}
.cell .info{display:block;position:absolute;top:4px;right:4px;width:24px;height:24px;padding:0;border-radius:50%;
  background:rgba(0,0,0,.5);color:#fff;border:0;font-size:12px;line-height:24px;text-align:center}
.empty{padding:28px 10px}
.more{width:100%;padding:10px;margin:14px 0}
.mbar{position:fixed;left:0;right:0;bottom:0;z-index:12;display:flex;gap:8px;align-items:center;
  padding:8px 12px calc(8px + env(safe-area-inset-bottom));background:var(--card);border-top:1px solid var(--line)}
.mbar .stat{flex:1;font-size:12px;line-height:1.3}
.mbar button{padding:8px 9px;font-size:12.5px;white-space:nowrap}
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
let ZONE='image',SID='',MONTH='',OFFSET=0,LIMIT=300,TOTAL=0,ALLOW=false,PENDING=null,CUR=-1;
const KINDS=new Set(['hd','main','thumb']);     // 类型多选，三类全选等于不筛
let LOADING=false, HAS_MORE=false;
function kindParam(){return KINDS.size>=3?'all':[...KINDS].join(',')||'all'}
function kindText(){
  const order=['hd','main','thumb'],map={hd:'原图',main:'普通图',thumb:'缩略图'};
  const ks=order.filter(k=>KINDS.has(k));
  return (!ks.length||ks.length===3)?'':' · '+ks.map(k=>map[k]).join('+');
}
const SEL=new Set(), INFO={};
let SEL_SIZE={}, DAYS=[], DAYMAP={}, DAY_EL={}, DAY_BASES={};   // 按天分组：汇总、已建区块、已取到的全部 base
let TIP_T=null, TIP_POS=null, TIP_SEQ=0, LOAD_SEQ=0;
let ZOOM=1, PANX=0, PANY=0, DRAG=null, SUPPRESS=false;
function applyZoom(){const b=$('big');b.style.transform=`translate(${PANX}px,${PANY}px) scale(${ZOOM})`;b.style.cursor=ZOOM>1?'grab':'default'}
function resetZoom(){ZOOM=1;PANX=0;PANY=0;applyZoom()}
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
  let s=0;for(const b of SEL)s+=SEL_SIZE[b]||0;
  $('selstat').textContent=`已选 ${SEL.size} 项 · ${fmt(s)}`;
  $('btn-export').disabled=SEL.size===0;$('btn-delete').disabled=SEL.size===0||!ALLOW;
  syncDayHeads();
}
function syncDayHeads(){
  Object.keys(DAY_EL).forEach(day=>{
    const sec=DAY_EL[day],ck=sec&&sec.querySelector('.dchk');
    if(!ck)return;
    const total=(DAYMAP[day]||{}).count||0;
    const bases=DAY_BASES[day]||ITEMS.filter(x=>x.day===day).map(x=>x.base);
    let sel=0;bases.forEach(b=>{if(SEL.has(b))sel++});
    const all=bases.length>0&&(total>0?sel>=total:sel===bases.length);
    ck.checked=all;
    ck.indeterminate=sel>0&&!all;
  });
}
// 桌面端鼠标框选：按下拖动出矩形，命中即勾选；Ctrl/Shift 拖动为追加
let BOX=null, JUST_DRAGGED=false, BOX_RAF=null, BOX_STAT=0;
function boxOverlay(){
  let el=$('boxsel');
  if(!el){el=document.createElement('div');el.id='boxsel';document.body.appendChild(el)}
  return el;
}
function boxRect(){
  return {left:Math.min(BOX.x0,BOX.x1),right:Math.max(BOX.x0,BOX.x1),
          top:Math.min(BOX.y0,BOX.y1),bottom:Math.max(BOX.y0,BOX.y1)};
}
function boxApply(){
  const r=boxRect();
  $('grid').querySelectorAll('.cell').forEach(c=>{
    const b=c.getBoundingClientRect();
    const hit=!(b.right<r.left||b.left>r.right||b.bottom<r.top||b.top>r.bottom);
    const on=hit||(BOX.base&&BOX.base.has(c.dataset.base));
    if(on)SEL.add(c.dataset.base);else SEL.delete(c.dataset.base);
    c.classList.toggle('sel',on);
    const ck=c.querySelector('.chk');if(ck)ck.checked=on;
  });
  const now=Date.now();
  if(now-BOX_STAT>120){BOX_STAT=now;updateStat()}   // 拖动中节流刷新底部统计
}
function boxScrollTick(){
  BOX_RAF=null;
  if(!BOX||!BOX.moved)return;
  const y=BOX.y1,h=innerHeight;
  let d=0;
  if(y>h-46)d=Math.min(28,Math.round((y-(h-46))/2));
  else if(y<46)d=-Math.min(28,Math.round((46-y)/2));
  if(d){
    const before=scrollY;
    scrollBy(0,d);
    if(scrollY!==before)boxApply();               // 页面滚动后命中范围要重算
    BOX_RAF=requestAnimationFrame(boxScrollTick);
  }
}
function setupBoxSelect(){
  if(MOBILE)return;
  const grid=$('grid');
  grid.addEventListener('mousedown',e=>{
    if(e.button!==0)return;
    if(e.target.closest('.dayhead'))return;             // 组头复选框不参与框选
    if(e.target.tagName==='INPUT')return;
    if($('box').classList.contains('on'))return;        // 预览层打开时不框选
    BOX={x0:e.clientX,y0:e.clientY,x1:e.clientX,y1:e.clientY,moved:false,
         add:e.ctrlKey||e.metaKey||e.shiftKey,base:new Set(SEL)};
    JUST_DRAGGED=false;
    e.preventDefault();                                 // 阻止图片被原生拖拽
  });
  addEventListener('mousemove',e=>{
    if(!BOX)return;
    if(!BOX.moved){
      if(Math.abs(e.clientX-BOX.x0)<4&&Math.abs(e.clientY-BOX.y0)<4)return;
      BOX.moved=true;
      document.body.classList.add('bxing');
      const el=boxOverlay();el.style.display='block';
      if(!BOX.add){                                     // 不按修饰键 = 覆盖选择
        SEL.clear();
        grid.querySelectorAll('.cell').forEach(c=>{c.classList.remove('sel');const ck=c.querySelector('.chk');if(ck)ck.checked=false});
      }
      hideTip();
      if(!BOX_RAF)BOX_RAF=requestAnimationFrame(boxScrollTick);
    }
    BOX.x1=Math.max(0,Math.min(innerWidth,e.clientX));
    BOX.y1=Math.max(0,Math.min(innerHeight,e.clientY));
    const r=boxRect(),el=boxOverlay();
    el.style.left=r.left+'px';el.style.top=r.top+'px';
    el.style.width=(r.right-r.left)+'px';el.style.height=(r.bottom-r.top)+'px';
    boxApply();
  },true);
  addEventListener('mouseup',e=>{
    if(!BOX)return;
    const moved=BOX.moved;
    BOX=null;
    if(BOX_RAF){cancelAnimationFrame(BOX_RAF);BOX_RAF=null}
    document.body.classList.remove('bxing');
    const el=$('boxsel');if(el)el.style.display='none';
    JUST_DRAGGED=moved;                                 // 紧跟其后的 click 不要再切换勾选
    updateStat();
    if(moved)setTimeout(()=>{JUST_DRAGGED=false},0);
  },true);
  addEventListener('mouseleave',()=>{                   // 鼠标移出窗口也要收尾
    if(!BOX)return;
    BOX=null;
    if(BOX_RAF){cancelAnimationFrame(BOX_RAF);BOX_RAF=null}
    document.body.classList.remove('bxing');
    const el=$('boxsel');if(el)el.style.display='none';
  });
}
async function init(){
  const k=await api('/api/status');ALLOW=k.allow_delete;
  $('keyinfo').textContent='密钥 '+k.key_desc;
  $('mode').textContent=ALLOW?(MOBILE?'可删除':'删除已启用（移入回收站）'):'只读模式';
  $('sid').onchange=()=>{SID=$('sid').value;clearSelection();showMonths()};
  const kf=$('kindfilter');
  if(kf)kf.addEventListener('change',e=>{
    const box=e.target.closest('input[type=checkbox]');
    if(!box)return;
    if(box.checked)KINDS.add(box.value);else KINDS.delete(box.value);
    if(!KINDS.size){box.checked=true;KINDS.add(box.value);return}   // 至少留一类
    if(MONTH)load(true);            // 重新拉取，旧选择一并清掉
  });
  $('tab-image').onclick=()=>switchZone('image');$('tab-video').onclick=()=>switchZone('video');
  $('btn-rescan').onclick=()=>startScan();
  if($('btn-logout'))$('btn-logout').onclick=logout;
  if($('btn-menu'))$('btn-menu').onclick=()=>$('panel').classList.toggle('open');
  setupAutoLoad();
  $('selall').onchange=e=>{
    $('grid').querySelectorAll('.cell').forEach(c=>{
      const b=c.dataset.base;
      if(e.target.checked)SEL.add(b);else SEL.delete(b);
      c.classList.toggle('sel',e.target.checked);
      const ck=c.querySelector('.chk');if(ck)ck.checked=e.target.checked;
    });
    updateStat();
  };
  setupBoxSelect();
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
  clearSelection();showMonths();
}
// 切换会话 / 分区时立刻清空界面与选择，避免旧网格配新 sid 造成「看到 A 删 B」
function clearSelection(){
  LOAD_SEQ++;                                  // 作废在途的旧请求，避免回来后画到新会话上
  SEL.clear();ITEMS=[];OFFSET=0;MONTH='';PENDING=null;
  SEL_SIZE={};DAYS=[];DAYMAP={};DAY_EL={};DAY_BASES={};
  $('grid').innerHTML='';$('stat').textContent='';HAS_MORE=false;
  updateStat();
}
async function showMonths(){
  const ms=ZONE==='image'?(SID?await api('/api/months?sid='+SID):[]):await api('/api/video_months');
  $('months').innerHTML=ms.map(m=>`<button data-m="${m}">${m}</button>`).join('');
  [...$('months').children].forEach(b=>b.onclick=()=>{MONTH=b.dataset.m;[...$('months').children].forEach(x=>x.classList.remove('on'));b.classList.add('on');load(true)});
  if(ms.length){MONTH=ms[ms.length-1];$('months').lastChild.classList.add('on');load(true)}else{reset('该分区没有内容')}
}
function reset(msg){LOAD_SEQ++;$('grid').innerHTML='';ITEMS=[];SEL_SIZE={};DAYS=[];DAYMAP={};DAY_EL={};DAY_BASES={};$('empty').textContent=msg;$('empty').style.display='block';$('stat').textContent='';SEL.clear();HAS_MORE=false;LOADING=false;showSpin(false);updateStat()}
async function fetchDays(){
  const u=ZONE==='image'
    ? `/api/days?zone=image&sid=${SID}&month=${MONTH}&kind=${kindParam()}`
    : `/api/days?zone=video&month=${MONTH}`;
  try{
    const arr=await api(u);
    DAYMAP={};arr.forEach(d=>{DAYMAP[d.day]=d});
    return arr;
  }catch(e){return []}
}
function ensureDay(day){
  if(DAY_EL[day])return DAY_EL[day];
  const m=DAYMAP[day]||{count:0,size:0};
  const sec=document.createElement('section');
  sec.className='daysec';sec.dataset.day=day;
  sec.innerHTML=`<div class="dayhead"><label class="dall"><input type="checkbox" class="dchk" title="勾选/取消这一天全部"><span>${day}</span></label><span class="dstat">${m.count} 项 · ${fmt(m.size)}</span></div><div class="dgrid"></div>`;
  sec.querySelector('.dchk').onchange=e=>toggleDay(day,e.target.checked,e.target);
  $('grid').appendChild(sec);
  sec._g=sec.querySelector('.dgrid');
  DAY_EL[day]=sec;
  return sec;
}
// 取某一天的全部 base（含分页里还没画出来的），点组头勾选时用
async function dayBases(day){
  if(DAY_BASES[day])return DAY_BASES[day];
  const mo=MONTH,sid=SID,zone=ZONE;
  const u=zone==='image'
    ? `/api/images?sid=${sid}&month=${mo}&offset=0&limit=0&kind=${kindParam()}&day=${day}`
    : `/api/videos?month=${mo}&offset=0&limit=0&day=${day}`;
  const d=await api(u);
  if(mo!==MONTH||sid!==SID||zone!==ZONE)return [];        // 请求期间环境已变，不写缓存
  d.items.forEach(x=>{SEL_SIZE[x.base]=x.size});
  DAY_BASES[day]=d.items.map(x=>x.base);
  return DAY_BASES[day];
}
async function toggleDay(day,on,el){
  const mo=MONTH,sid=SID,zone=ZONE;
  if(el)el.disabled=true;
  try{
    const bases=await dayBases(day);
    if(mo!==MONTH||sid!==SID||zone!==ZONE){if(el)el.checked=!on;return}   // 期间换了月份/会话，作废
    const set=new Set(bases);
    bases.forEach(b=>{on?SEL.add(b):SEL.delete(b)});
    $('grid').querySelectorAll('.cell').forEach(c=>{
      if(!set.has(c.dataset.base))return;
      c.classList.toggle('sel',on);
      const ck=c.querySelector('.chk');if(ck)ck.checked=on;
    });
    updateStat();
  }catch(e){
    if(el)el.checked=!on;
    alert('读取该日期失败：'+e.message);
  }finally{if(el)el.disabled=false;syncDayHeads()}
}
function showSpin(on){
  const el=$('autoload');
  if(el)el.style.display=on?'flex':'none';
}
function maybeLoadMore(){
  if(LOADING||!HAS_MORE||!MONTH)return;
  const box=$('box');
  if(box&&box.classList.contains('on'))return;      // 大图预览时不后台翻页
  load(false);
}
function autoContinue(){
  // 一页填不满屏幕时 observer 不会再触发，补一次判断
  if(LOADING||!HAS_MORE||!MONTH)return;
  const el=$('sentinel');
  if(el&&el.getBoundingClientRect().top<innerHeight+400)setTimeout(maybeLoadMore,80);
}
function setupAutoLoad(){
  const el=$('sentinel');
  if(!el)return;
  if('IntersectionObserver' in window){
    new IntersectionObserver(es=>{
      if(es.some(e=>e.isIntersecting))maybeLoadMore();
    },{rootMargin:'400px 0px'}).observe(el);
  }else{
    addEventListener('scroll',()=>{
      if(innerHeight+scrollY>=document.body.scrollHeight-500)maybeLoadMore();
    },{passive:true});
  }
}
async function load(fresh){
  const seq=++LOAD_SEQ;                       // 只认最后一次请求，过期结果直接丢
  LOADING=true;if(!fresh)showSpin(true);
  try{
  if(fresh){
    OFFSET=0;$('grid').innerHTML='';ITEMS=[];SEL.clear();
    SEL_SIZE={};DAYMAP={};DAY_EL={};DAY_BASES={};
    DAYS=await fetchDays();
    if(seq!==LOAD_SEQ)return;
  }
  const start=OFFSET;
  const u=ZONE==='image'?`/api/images?sid=${SID}&month=${MONTH}&offset=${start}&limit=${LIMIT}&kind=${kindParam()}`:`/api/videos?month=${MONTH}&offset=${start}&limit=${LIMIT}`;
  const d=await api(u);
  if(seq!==LOAD_SEQ)return;                   // 期间已换月份/会话，丢弃这一页
  TOTAL=d.total;
  $('empty').style.display=TOTAL?'none':'block';
  if(!TOTAL){reset('该月份没有内容');return}
  if(!d.items.length){HAS_MORE=false;return}
  const seen=new Set(ITEMS.map(x=>x.base));   // 分页期间目录变动会产生重复，跳过去重
  d.items.forEach(it=>{
    SEL_SIZE[it.base]=it.size;                // 未加载的分页项也要能算大小
    if(seen.has(it.base))return;
    seen.add(it.base);
    ITEMS.push(it);
    const c=document.createElement('div');c.className='cell';c.dataset.base=it.base;
    const src=ZONE==='image'?`/api/img?sid=${SID}&month=${MONTH}&base=${encodeURIComponent(it.base)}&kind=thumb`:`/api/video_thumb?month=${MONTH}&base=${encodeURIComponent(it.base)}`;
    const kindTag = ZONE==='video'
      ? '<span class="kt kt-video">视频</span>'
      : it.has_hd ? '<span class="kt kt-hd">原图</span>'
      : it.has_main ? '<span class="kt kt-main">普通图</span>'
      : '<span class="kt kt-thumb">缩略图</span>';
    c.innerHTML=`<input type="checkbox" class="chk" ${SEL.has(it.base)?'checked':''}><img loading="lazy" src="${src}" alt=""><div class="meta"><span class="name">${it.base.slice(0,10)} · ${fmt(it.size)}</span>${kindTag}</div>${ZONE==='video'?'<div class="play"><span>▶</span></div>':''}${MOBILE?'<button class="info" aria-label="详情">i</button>':''}`;
    const ck=c.querySelector('.chk');
    const toggle=on=>{if(on)SEL.add(it.base);else SEL.delete(it.base);c.classList.toggle('sel',on);if(ck)ck.checked=on;updateStat()};
    if(ck)ck.onclick=e=>{e.stopPropagation();toggle(e.target.checked)};
    c.onclick=e=>{if(JUST_DRAGGED)return;if(e.target===ck||e.target.closest('.info'))return;toggle(!SEL.has(it.base))};
    c.ondblclick=e=>{if(JUST_DRAGGED)return;if(e.target===ck||e.target.closest('.info'))return;e.preventDefault();openBox(it)};
    if(MOBILE){
      c.querySelector('.info').onclick=e=>{e.stopPropagation();showTip(it.base)};
    }else{
      c.onmouseenter=e=>{if(BOX&&BOX.moved)return;TIP_POS={clientX:e.clientX,clientY:e.clientY};clearTimeout(TIP_T);TIP_T=setTimeout(()=>showTip(it.base,TIP_POS),500)};
      c.onmousemove=e=>{TIP_POS={clientX:e.clientX,clientY:e.clientY};if($('tip').style.display==='block')moveTip(TIP_POS)};
      c.onmouseleave=()=>{clearTimeout(TIP_T);hideTip()};
    }
    ensureDay(it.day)._g.appendChild(c);
  });
  OFFSET=start+d.items.length;
  $('stat').textContent=`${MONTH}${kindText()} · 共 ${TOTAL} 项 / ${DAYS.length} 天 · 已显示 ${OFFSET} 项`;
  HAS_MORE=OFFSET<TOTAL;
  $('selall').checked=false;updateStat();
  }finally{
    if(seq===LOAD_SEQ){LOADING=false;showSpin(false);autoContinue()}
  }
}
function tipHtml(m){
  const dim=m.width?`${m.width} × ${m.height}`:'未知';
  const dur=m.duration?`${m.duration} 秒`:'—';
  const rows=m.files.map(f=>`<div><span class="k">路径</span><b>${f.path}</b><br><span class="k">日期时间</span>${f.mtime_str}　<span class="k">大小</span>${fmt(f.size)}${f.nlink>1?'　<span style="color:#dc2626">硬链接 '+f.nlink+'</span>':''}</div>`).join('<hr style="border:0;border-top:1px solid #eee">');
  return `<div><span class="k">分区</span><b>${ZONE==='image'?'图片':'视频'}</b>　<span class="k">格式</span><b>${m.format}</b></div><div><span class="k">像素尺寸</span><b>${dim}</b>　<span class="k">时长</span>${dur}　<span class="k">合计</span>${fmt(m.total_size)}</div><hr style="border:0;border-top:1px solid #eee">${rows}`;
}
async function showTip(base,e){
  const seq=++TIP_SEQ;                         // 快速划过时只显示最后一张的信息
  const key=ZONE+'|'+SID+'|'+MONTH+'|'+base;
  let m=INFO[key];
  if(!m){
    m=await api(`/api/info?zone=${ZONE}&sid=${SID}&month=${MONTH}&base=${encodeURIComponent(base)}`);
    if(seq!==TIP_SEQ)return;
    INFO[key]=m;
  }
  if(seq!==TIP_SEQ)return;
  $('tip').innerHTML=tipHtml(m)+(MOBILE?'<div style="margin-top:10px;color:#6b7280;font-size:12px">点击空白处关闭</div>':'');
  if(MOBILE){$('tip').classList.add('on');$('tipmask').classList.add('on')}
  else{$('tip').style.display='block';moveTip(e)}
}
function moveTip(e){const t=$('tip');const x=Math.min(e.clientX+16,innerWidth-480),y=Math.min(e.clientY+16,innerHeight-260);t.style.left=Math.max(8,x)+'px';t.style.top=Math.max(8,y)+'px'}
function hideTip(){
  clearTimeout(TIP_T);TIP_T=null;TIP_SEQ++;
  $('tip').classList.remove('on');$('tipmask').classList.remove('on');
  if(!MOBILE)$('tip').style.display='none';
}
function renderBox(it){
  if(ZONE==='image'){
    $('vid').style.display='none';$('vid').pause();$('big').style.display='block';
    $('big').src=`/api/img?sid=${SID}&month=${MONTH}&base=${encodeURIComponent(it.base)}&kind=full`;
    resetZoom();
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
function closeBox(){$('box').classList.remove('on');$('big').src='';$('vid').pause();$('vid').src='';resetZoom()}
// 图片预览：滚轮缩放、放大后左键拖动、双击复位
$('big').addEventListener('wheel',e=>{
  if(ZONE!=='image'||!$('box').classList.contains('on'))return;
  e.preventDefault();
  const nz=Math.min(8,Math.max(1,ZOOM*(e.deltaY<0?1.15:1/1.15)));
  if(nz===ZOOM)return;
  ZOOM=nz;if(ZOOM===1){PANX=0;PANY=0}
  applyZoom();
},{passive:false});
$('big').addEventListener('mousedown',e=>{
  if(ZONE!=='image'||ZOOM<=1)return;
  DRAG={x:e.clientX,y:e.clientY,px:PANX,py:PANY};
  $('big').style.cursor='grabbing';$('big').style.transition='none';e.preventDefault();
});
addEventListener('mousemove',e=>{
  if(!DRAG)return;
  if(Math.abs(e.clientX-DRAG.x)>3||Math.abs(e.clientY-DRAG.y)>3)DRAG.moved=true;
  PANX=DRAG.px+(e.clientX-DRAG.x);PANY=DRAG.py+(e.clientY-DRAG.y);applyZoom();
});
addEventListener('mouseup',()=>{
  if(!DRAG)return;
  const moved=DRAG.moved;DRAG=null;$('big').style.transition='';applyZoom();
  if(moved){SUPPRESS=true;setTimeout(()=>SUPPRESS=false,0)}
});
$('big').addEventListener('dblclick',e=>{e.stopPropagation();resetZoom()});
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
let delTimer=null;
async function pollDelete(){
  clearTimeout(delTimer);
  let s;
  try{s=await api('/api/delete/status')}catch(e){return}
  const fill=$('dfill');
  if(fill){
    const pct=s.total?Math.min(100,Math.round(s.done*100/s.total)):100;
    fill.style.width=pct+'%';
    const n=$('dnum');if(n)n.innerHTML=`已处理 <b>${s.done}</b> / ${s.total}（${pct}%）`;
    const c=$('dcur');if(c)c.textContent=s.current?('当前：'+s.current):(s.finished?'已完成':'准备中…');
    const b=$('dbytes');
    if(b)b.textContent=`${fmt(s.bytes_done)} / ${fmt(s.bytes_total)}`+(s.failed?`　失败 ${s.failed} 个`:'');
  }
  if(s.finished){
    const r=s.result||{};
    load(true);
    modal('删除结果',`<div class="result">已移入回收站：${r.deleted} 个文件（${r.batches} 批）\n失败：${r.failed} 个${r.stopped_early?'\n已中止剩余批次':''}\n日志：${r.log}\n\n可从系统回收站还原。</div>`,[btn('关闭','',closeModal)]);
    return;
  }
  delTimer=setTimeout(pollDelete,300);
}
function showDeleteProgress(total,bytes){
  modal('正在移入回收站（第二步：执行中）',`<div class="dprog">
    <div class="num" id="dnum">已处理 <b>0</b> / ${total}（0%）</div>
    <div class="track"><div id="dfill"></div></div>
    <div class="cur" id="dcur">准备中…</div>
    <div class="num" id="dbytes" style="color:var(--sub)">0 KB / ${fmt(bytes)}</div>
  </div>`,[btn('关闭','',()=>{clearTimeout(delTimer);closeModal();load(true)})]);
  pollDelete();
}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function openLogs(){
  let d;
  try{d=await api('/api/logs?limit=300')}
  catch(e){modal('操作日志',`<div class="result">${esc(e.message)}</div>`,[btn('关闭','',closeModal)]);return}
  const rows=d.items.length?d.items.map(it=>{
    const files=(it.files&&it.files.length)
      ? `<div class="lfiles">${it.files.map(esc).join('、')}${it.count>it.files.length?` 等 ${it.count} 个`:''}</div>` : '';
    return `<div class="lrow${it.ok===false?' bad':''}">
      <div class="lhead"><span class="ltime">${esc(it.time)}</span><span class="lip">${esc(it.ip)}</span><span class="ltag">${esc(it.label||it.action)}</span></div>
      ${it.detail?`<div class="ldetail">${esc(it.detail)}</div>`:''}${files}</div>`;
  }).join(''):'<div class="lrow" style="color:#6b7280">暂无操作记录</div>';
  const body=`<div class="lbar">当前来源 IP：<b>${esc(d.ip)}</b>　共 <b>${d.total}</b> 条（倒序，最多显示 300 条）</div>
    <div class="llist">${rows}</div>`;
  modal('操作日志',body,[
    btn('刷新','',openLogs),
    btn('一键清空','danger',()=>clearLogs(d.clear_word,d.total)),
    btn('关闭','',closeModal)
  ]);
}
function clearLogs(word,total){
  const body=`<div class="warn">⚠️ 将删除全部 ${total} 条操作记录，不可恢复；只会留下一条「清空日志」的痕迹。</div>
    <div>请输入 <b>${word}</b> 完成二次确认：<br><input id="lword" style="width:320px;margin-top:6px" autocomplete="off" placeholder="手工输入确认词"></div>`;
  modal('清空操作日志（二次确认）',body,[
    btn('取消','',openLogs),
    btn('确认清空','danger',async()=>{
      const w=$('lword').value.trim();
      if(w!==word){alert('确认词不正确，未清空任何日志');return}
      try{const r=await post('/api/logs/clear',{confirm:w});alert(`已清空 ${r.cleared} 条记录`);openLogs()}
      catch(e){alert(e.message)}
    })
  ]);
}
if($('btn-logs'))$('btn-logs').onclick=openLogs;
$('btn-delete').onclick=async()=>{
  if(!SEL.size||!ALLOW)return;
  try{
    const p=await post('/api/delete/preview',stub());PENDING=p.token;
    const chosen=new Set(p.kinds.filter(k=>k.default).map(k=>k.kind));
    const krows=p.kinds.map(k=>`<label class="krow${chosen.has(k.kind)?' on':''}" data-kind="${k.kind}">
        <input type="checkbox"${chosen.has(k.kind)?' checked':''}>
        <span class="ktxt"><span class="klabel">${k.label}</span><span class="kdesc">${k.desc}</span></span>
        <span class="kstat">${k.count} 个 · ${fmt(k.size)}</span>
      </label>`).join('');
    const body=`<div class="warn">⚠️ ${p.warning}</div>
      <div class="result">分组 <b>${p.group_count}</b> 项，共 ${p.file_count} 个文件，合计 ${fmt(p.total_size)}${p.hardlinked_files?`<br><span style="color:#dc2626">其中 ${p.hardlinked_files} 个是硬链接文件，删除后不一定立刻释放空间</span>`:''}</div>
      <div style="margin:12px 0 6px;font-weight:600">选择要删除的文件类型</div>
      <div id="klist">${krows}</div>
      <div class="result" id="ksum" style="margin:8px 0 10px;color:#b91c1c"></div>
      <div id="dlist" class="list" style="max-height:180px;margin-bottom:12px"></div>
      <div>请输入 <b>${p.confirm_word}</b> 完成二次确认：<br><input id="cword" style="width:320px;margin-top:6px" autocomplete="off" placeholder="手工输入确认词"></div>`;
    const refresh=()=>{
      const files=p.files.filter(f=>chosen.has(f.kind||'main'));
      const size=files.reduce((a,f)=>a+f.size,0);
      $('ksum').innerHTML=files.length?`将删除 <b>${files.length}</b> 个文件，合计 <b>${fmt(size)}</b>`:'<span style="color:#6b7280">未选择任何类型，不会删除文件</span>';
      $('dlist').innerHTML=files.slice(0,500).map(f=>`${f.path}　(${fmt(f.size)})`).join('<br>')
        +(files.length>500?`<br>… 其余 ${files.length-500} 个未列出`:'');
    };
    modal('删除前确认（第一步：清单与风险）',body,[
      btn('取消','',closeModal),
      btn('第二步：移入回收站','danger',async()=>{
        const w=$('cword').value.trim();
        if(w!==p.confirm_word){alert('确认词不正确，未执行任何删除');return}
        if(!chosen.size){alert('请至少勾选一类文件');return}
        let r;
        try{r=await post('/api/delete/commit',{token:p.token,confirm:w,kinds:[...chosen]})}
        catch(e){modal('删除失败',`<div class="result">${e.message}</div>`,[btn('关闭','',closeModal)]);return}
        showDeleteProgress(r.total,r.bytes_total);
      })
    ]);
    $('klist').addEventListener('change',e=>{
      const row=e.target.closest('.krow');if(!row)return;
      const k=row.dataset.kind;
      if(e.target.checked)chosen.add(k);else chosen.delete(k);
      row.classList.toggle('on',e.target.checked);
      refresh();
    });
    refresh();
  }catch(e){modal('无法预览删除',`<div class="result">${e.message}</div>`,[btn('关闭','',closeModal)])}
};
$('box').onclick=e=>{if(e.target.id==='box'&&!SUPPRESS)closeBox()};
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
.pwbox{position:relative}
.pwbox input{padding-right:46px}
.pwbox .eye{position:absolute;right:6px;top:50%;transform:translateY(-50%);width:32px;height:32px;margin:0;padding:0;
  background:transparent;border:0;border-radius:6px;color:#8b929c;display:flex;align-items:center;justify-content:center;cursor:pointer}
.pwbox .eye:hover{background:#f1f3f6;color:#1f2329}
.pwbox .eye svg{display:block}
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
    <div class="pwbox"><input id="pw" type="password" autocomplete="current-password" placeholder="请输入密码"><button class="eye" type="button" id="eye" aria-label="显示密码" title="显示密码"><svg id="eyeicon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg></button></div>
    __CONFIRM__
    <button id="go" type="submit">__ACTION__</button>
  </form>
  <div class="msg" id="msg"></div>
  <div class="hint">__HINT__</div>
</div>
<script>
const MODE=__MODE__,BAN=__BAN__;
const $=id=>document.getElementById(id);
const EYE_OPEN='<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>';
const EYE_SHUT='<path d="M17.9 17.9A10.1 10.1 0 0 1 12 20c-7 0-11-8-11-8a18.5 18.5 0 0 1 5.1-5.9M9.9 4.2A9.1 9.1 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.2 3.2M14.1 14.1a3 3 0 1 1-4.2-4.2"/><line x1="1" y1="1" x2="23" y2="23"/>';
$('eye').onclick=()=>{
  const p=$('pw'),on=p.type==='password';
  p.type=on?'text':'password';
  $('eyeicon').innerHTML=on?EYE_SHUT:EYE_OPEN;
  $('eye').title=$('eye').getAttribute('aria-label')=on?'隐藏密码':'显示密码';
  p.focus();
};
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
        hint = ""                                 # 规则提示已移到「操作日志」里体现（含来源 IP）
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
