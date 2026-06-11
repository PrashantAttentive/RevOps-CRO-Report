#!/usr/bin/env python3
"""
app.py — Railway web service for the RevOps conversion report.

Routes:
  GET  /         -> the interactive report page
  GET  /data     -> cached report data as JSON (auto-refreshes if stale)
  POST /refresh  -> forces a live HubSpot pull, returns fresh JSON

The page fetches /data on load and calls /refresh when the user clicks Refresh.
Data is cached in memory with a freshness window (CACHE_TTL) so ordinary visits
are always reasonably current without a manual click; the button forces an
immediate live pull.

Env: HUBSPOT_TOKEN (private-app token).
Start: uvicorn app:app --host 0.0.0.0 --port $PORT
"""

import time
import base64
import threading

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from report_data import build_report_data

app = FastAPI()

CACHE_TTL = 1800  # seconds; visits older than this trigger an auto-refresh
_cache = {"data": None, "ts": 0.0}
_lock = threading.Lock()


def get_data(force=False):
    with _lock:
        stale = _cache["data"] is None or (time.time() - _cache["ts"]) > CACHE_TTL
        if force or stale:
            _cache["data"] = build_report_data()
            _cache["ts"] = time.time()
        return _cache["data"]


@app.get("/data")
def data():
    try:
        return JSONResponse(get_data(False))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/refresh")
def refresh():
    try:
        return JSONResponse(get_data(True))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(PAGE.replace("__FAVICON__", FAVICON_URI))


# Tab favicon: perched crow (option 1), static.
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<ellipse cx="30" cy="37" rx="15" ry="11" fill="#23262E"/>'
    '<circle cx="17" cy="25" r="8.5" fill="#23262E"/>'
    '<polygon points="9,23 1,26.5 9,30" fill="#D85A30"/>'
    '<polygon points="44,34 61,28 57,42" fill="#23262E"/>'
    '<circle cx="15" cy="23" r="1.8" fill="#F3F1EA"/>'
    '<path d="M31,30 C41,25 53,30 50,41 C43,43 34,39 29,32 Z" fill="#3A3F4A"/>'
    '</svg>'
)
FAVICON_URI = "data:image/svg+xml;base64," + base64.b64encode(FAVICON_SVG.encode()).decode()


PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RevOps Conversion Report</title>
<link rel="icon" type="image/svg+xml" href="__FAVICON__">
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#2C2C2A;max-width:960px;margin:0 auto;padding:24px;background:#fff;}
h1{font-size:20px;font-weight:600;margin:0 0 4px;}
.hdr{display:flex;align-items:center;gap:14px;}
.logo{flex:none;width:72px;height:72px;}
.meta{font-size:11px;color:#888780;}
.spacer{flex:1;}
.refresh{display:flex;align-items:center;gap:8px;background:#185FA5;color:#fff;border:none;border-radius:6px;padding:8px 14px;font-size:13px;font-weight:500;cursor:pointer;font-family:inherit;}
.refresh:hover{background:#13548f;}
.refresh:disabled{opacity:.6;cursor:default;}
.tabs{display:flex;gap:4px;border-bottom:1px solid #D3D1C7;margin:16px 0 12px;}
.tb{padding:8px 16px;font-size:13px;font-weight:500;color:#5F5E5A;background:none;border:none;border-bottom:2px solid transparent;cursor:pointer;font-family:inherit;}
.tb:hover{color:#2C2C2A;}.tb.active{color:#185FA5;border-bottom-color:#185FA5;}
.controls{display:flex;flex-wrap:wrap;gap:18px;align-items:center;margin-bottom:6px;}
.seg{display:inline-flex;border:1px solid #D3D1C7;border-radius:6px;overflow:hidden;}
.sg{padding:6px 12px;font-size:12px;color:#5F5E5A;background:#fff;border:none;cursor:pointer;font-family:inherit;border-right:1px solid #D3D1C7;}
.sg:last-child{border-right:none;}.sg:hover{background:#F4F3EE;}.sg.active{background:#185FA5;color:#fff;}
.ct{font-size:15px;font-weight:600;margin-bottom:4px;}
.lg{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:6px;font-size:11px;color:#5F5E5A;}
.lg span{display:flex;align-items:center;gap:5px;}.lg i{width:15px;height:0;display:inline-block;}
.scroll{overflow-x:auto;flex:1;}
.inner{position:relative;height:300px;}
.chartblock{display:flex;align-items:stretch;}
.yaxis{flex:none;width:44px;height:300px;}
.hint{font-size:10px;color:#A8A6A0;margin:-4px 0 22px;}
@keyframes flap5{0%,100%{transform:rotate(-14deg)}50%{transform:rotate(10deg)}}
@keyframes draw5{0%{stroke-dashoffset:90}60%,100%{stroke-dashoffset:0}}
@keyframes spin{to{transform:rotate(360deg)}}
.wing5{transform-origin:50px 15px;animation:flap5 0.65s ease-in-out infinite}
.line5{stroke-dasharray:90;animation:draw5 2.8s ease-in-out infinite}
.spinning{animation:spin .8s linear infinite}
.egg-bubble{position:fixed;background:rgba(35,38,46,0.55);color:#fff;padding:6px 12px;border-radius:14px;font-size:12px;font-weight:500;opacity:0;transform:translate(-50%,calc(-100% + 6px)) scale(.96);transition:opacity .2s ease,transform .2s ease;pointer-events:none;z-index:1000;white-space:nowrap;backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);}
.egg-bubble::after{content:'';position:absolute;left:50%;bottom:-5px;transform:translateX(-50%);border-left:5px solid transparent;border-right:5px solid transparent;border-top:5px solid rgba(35,38,46,0.55);}
.egg-bubble.show{opacity:.85;transform:translate(-50%,-100%) scale(1);}
</style></head><body>
<div class="hdr">
  <svg class="logo" viewBox="0 0 64 64" role="img" aria-label="crow perched atop a rising trend line">
    <polyline class="line5" points="5,55 20,47 34,49 49,20" fill="none" stroke="#185FA5" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    <polygon points="44,16 37,13 44,20" fill="#23262E"/>
    <ellipse cx="50" cy="16" rx="6.5" ry="5" fill="#23262E"/>
    <circle cx="55" cy="12" r="4" fill="#23262E"/>
    <polygon points="59,11 65,12.5 59,14" fill="#D85A30"/>
    <circle cx="56" cy="11" r="1" fill="#F3F1EA"/>
    <line x1="48" y1="20" x2="47" y2="25" stroke="#23262E" stroke-width="1.6"/>
    <line x1="52" y1="20" x2="53" y2="25" stroke="#23262E" stroke-width="1.6"/>
    <path class="wing5" d="M50,15 C54,12 60,14 58,20 C54,21 50,19 48,16 Z" fill="#3A3F4A"/>
  </svg>
  <div>
    <h1>RevOps Weekly Conversion Report</h1>
    <div class="meta">Beam AI Deals &middot; <span id="gen">loading&hellip;</span></div>
  </div>
  <div class="spacer"></div>
  <button class="refresh" id="refreshBtn"><svg id="refreshIcon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg><span id="refreshLabel">Refresh</span></button>
</div>
<div class="tabs"><button class="tb active" data-u="Overall">Overall</button><button class="tb" data-u="ACE">ACE</button><button class="tb" data-u="SPADE">SPADE</button></div>
<div class="controls">
  <div class="seg" data-group="gran"><button class="sg active" data-v="weekly">Weekly</button><button class="sg" data-v="monthly">Monthly</button></div>
  <div class="seg" data-group="basis"><button class="sg active" data-v="with">Total incl. Cancelled</button><button class="sg" data-v="without">Total excl. Cancelled</button></div>
</div>
<div id="t1" class="ct"></div>
<div class="lg"><span><i style="border-top:2px solid #185FA5;"></i>DCC / total</span><span><i style="border-top:2px dashed #0F6E56;"></i>QDD / total</span><span><i style="border-top:2px dotted #D85A30;"></i>Pilots / total</span></div>
<div class="chartblock"><div class="yaxis"><canvas id="c1y"></canvas></div><div class="scroll" id="s1"><div class="inner" id="in1"><canvas id="c1"></canvas></div></div></div>
<div class="hint" id="hint1"></div>
<div class="ct">Conversion as % of DCC</div>
<div class="lg"><span><i style="border-top:2px dashed #0F6E56;"></i>QDD / DCC</span><span><i style="border-top:2px dotted #D85A30;"></i>Pilots / DCC</span></div>
<div class="chartblock"><div class="yaxis"><canvas id="c2y"></canvas></div><div class="scroll" id="s2"><div class="inner" id="in2"><canvas id="c2"></canvas></div></div></div>
<div class="hint" id="hint2"></div>
<div class="egg-bubble" id="eggBubble">Hey Harsh!</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
<script>
Chart.register(ChartDataLabels);
let DATA=null,gran='weekly',unit='Overall',basis='with';
const add=(a,b)=>a.map((v,i)=>v+b[i]);
const sel=(d,m)=>unit==='Overall'?add(d.ACE[m],d.SPADE[m]):d[unit][m];
const pct=(a,b)=>a.map((v,i)=>b[i]?Math.round(v/b[i]*1000)/10:null);
const ymax=arrs=>{let m=0;arrs.forEach(a=>a.forEach(v=>{if(v!=null&&v>m)m=v;}));return Math.min(100,Math.ceil((m+8)/10)*10);};
const opts=()=>({responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false,callbacks:{label:c=>c.dataset.label+': '+c.parsed.y+'%'}},datalabels:{display:true,align:'top',anchor:'end',offset:3,color:c=>c.dataset.borderColor,font:{size:9,weight:500},formatter:v=>v===null?'':v+'%'}},scales:{x:{ticks:{autoSkip:false,maxRotation:0,font:{size:10}},grid:{display:false}},y:{min:0,grid:{color:'rgba(128,128,128,0.15)'},border:{display:false},ticks:{display:true,color:'rgba(0,0,0,0)',font:{size:10},callback:v=>v+'%'},afterFit:function(a){a.width=0;}}}});
const axisOpts=()=>({responsive:true,maintainAspectRatio:false,animation:false,plugins:{legend:{display:false},tooltip:{enabled:false},datalabels:{display:false}},scales:{x:{display:true,grid:{display:false},border:{display:false},ticks:{display:true,color:'rgba(0,0,0,0)',font:{size:10},maxRotation:0,autoSkip:false}},y:{min:0,grid:{display:false},border:{display:false},ticks:{callback:v=>v+'%',font:{size:10}}}});
const mk=(id,ds)=>new Chart(document.getElementById(id),{type:'line',data:{labels:[],datasets:ds},options:opts()});
const c1=mk('c1',[{label:'DCC / total',borderColor:'#185FA5',backgroundColor:'#185FA5',pointRadius:3,tension:0.3,data:[]},{label:'QDD / total',borderColor:'#0F6E56',backgroundColor:'#0F6E56',borderDash:[6,4],pointRadius:3,tension:0.3,data:[]},{label:'Pilots / total',borderColor:'#D85A30',backgroundColor:'#D85A30',borderDash:[2,3],pointRadius:4,tension:0.3,data:[]}]);
const c2=mk('c2',[{label:'QDD / DCC',borderColor:'#0F6E56',backgroundColor:'#0F6E56',borderDash:[6,4],pointRadius:3,tension:0.3,data:[]},{label:'Pilots / DCC',borderColor:'#D85A30',backgroundColor:'#D85A30',borderDash:[2,3],pointRadius:4,tension:0.3,data:[]}]);
const mkAxis=id=>new Chart(document.getElementById(id),{type:'line',data:{labels:[''],datasets:[{data:[]}]},options:axisOpts()});
const c1y=mkAxis('c1y'),c2y=mkAxis('c2y');
function setWidth(){
  const n=DATA[gran].labels.length;
  const w=gran==='weekly'?Math.max(720,n*66)+'px':'100%';
  document.getElementById('in1').style.width=w;
  document.getElementById('in2').style.width=w;
  const scrolls=gran==='weekly';
  document.getElementById('hint1').textContent=scrolls?'scroll horizontally to see all weeks \u2192':'';
  document.getElementById('hint2').textContent=scrolls?'scroll horizontally to see all weeks \u2192':'';
}
function render(){
  if(!DATA)return;
  const d=DATA[gran];
  const total=sel(d,basis==='with'?'demos':'demos_nc');
  const dcc=sel(d,'dcc'),qdd=sel(d,'qdd'),pil=sel(d,'pilots');
  const a1=[pct(dcc,total),pct(qdd,total),pct(pil,total)],a2=[pct(qdd,dcc),pct(pil,dcc)];
  setWidth();
  c1.data.labels=d.labels;c2.data.labels=d.labels;
  c1.data.datasets.forEach((ds,i)=>ds.data=a1[i]);
  c2.data.datasets.forEach((ds,i)=>ds.data=a2[i]);
  c1.options.scales.y.max=ymax(a1);c2.options.scales.y.max=ymax(a2);
  c1y.options.scales.y.max=ymax(a1);c2y.options.scales.y.max=ymax(a2);
  c1.resize();c2.resize();c1.update();c2.update();
  c1y.resize();c2y.resize();c1y.update();c2y.update();
  if(gran==='weekly'){requestAnimationFrame(()=>{const s1=document.getElementById('s1'),s2=document.getElementById('s2');s1.scrollLeft=s1.scrollWidth;s2.scrollLeft=s2.scrollWidth;});}
  else{document.getElementById('s1').scrollLeft=0;document.getElementById('s2').scrollLeft=0;}
  document.getElementById('t1').textContent='Conversion as % of total demos ('+(basis==='with'?'incl.':'excl.')+' Cancelled)';
}
// sync horizontal scroll between the two charts
const s1=document.querySelectorAll('.scroll')[0],s2=document.querySelectorAll('.scroll')[1];
s1.addEventListener('scroll',()=>{s2.scrollLeft=s1.scrollLeft;});
s2.addEventListener('scroll',()=>{s1.scrollLeft=s2.scrollLeft;});
async function load(force){
  const btn=document.getElementById('refreshBtn'),ic=document.getElementById('refreshIcon'),lb=document.getElementById('refreshLabel');
  btn.disabled=true;ic.classList.add('spinning');lb.textContent=force?'Refreshing\u2026':'Loading\u2026';
  try{
    const r=await fetch(force?'/refresh':'/data',{method:force?'POST':'GET'});
    const j=await r.json();
    if(j.error){document.getElementById('gen').textContent='error: '+j.error;}
    else{DATA=j;document.getElementById('gen').textContent='updated '+j.generated;render();}
  }catch(e){document.getElementById('gen').textContent='error loading data';}
  btn.disabled=false;ic.classList.remove('spinning');lb.textContent='Refresh';
}
function popEgg(el){
  const b=document.getElementById('eggBubble'),r=el.getBoundingClientRect();
  b.style.left=(r.left+r.width/2)+'px';b.style.top=r.top+'px';
  b.classList.add('show');clearTimeout(b._t);
  b._t=setTimeout(()=>b.classList.remove('show'),500);
}
document.getElementById('refreshBtn').addEventListener('click',()=>load(true));
document.querySelectorAll('.tb').forEach(t=>t.addEventListener('click',()=>{document.querySelectorAll('.tb').forEach(x=>x.classList.remove('active'));t.classList.add('active');unit=t.dataset.u;render();}));
document.querySelectorAll('.seg').forEach(g=>g.querySelectorAll('.sg').forEach(b=>b.addEventListener('click',()=>{g.querySelectorAll('.sg').forEach(x=>x.classList.remove('active'));b.classList.add('active');if(g.dataset.group==='gran')gran=b.dataset.v;else basis=b.dataset.v;if(g.dataset.group==='basis'&&b.dataset.v==='without')popEgg(b);render();})));
load(false);
</script></body></html>
"""
