import os, secrets, time, math, re
from pathlib import Path
from urllib.parse import urlencode
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from pydantic import BaseModel

app=FastAPI(title='ClipForge')
SESSIONS={}; STATES={}
OUT=Path('/tmp/clipforge'); OUT.mkdir(exist_ok=True)

HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>ClipForge</title><style>
*{box-sizing:border-box}body{margin:0;background:#090a0f;color:#f6f7fb;font:15px system-ui,Segoe UI,sans-serif}main{max-width:980px;margin:auto;padding:34px 18px}.hero{padding:48px 0}.tag{color:#a98cff;font-weight:800;letter-spacing:.12em;font-size:12px}h1{font-size:clamp(42px,8vw,78px);line-height:.95;margin:12px 0}h1 span{color:#9b6cff}p{color:#9ba1b2;line-height:1.55}.card{background:#12141b;border:1px solid #292d3a;border-radius:18px;padding:22px;margin:16px 0}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}button,a.btn{background:#8257ff;color:white;border:0;border-radius:10px;padding:12px 16px;font-weight:800;text-decoration:none;cursor:pointer}.secondary{background:#222633!important}.pill{padding:7px 10px;border:1px solid #343949;border-radius:99px;color:#a8adbb;font-size:12px}.clips{display:grid;gap:10px;margin-top:16px}.clip{background:#181b24;border:1px solid #2c3040;border-radius:12px;padding:14px;display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center}.score{font-size:24px;color:#59eda9;font-weight:900}.small{font-size:12px;color:#8f95a7}.hidden{display:none}video{width:min(320px,100%);aspect-ratio:9/16;background:#000;border-radius:16px}code{background:#0d0f14;border:1px solid #2a2e3b;padding:10px;border-radius:8px;display:block;overflow:auto}.warn{color:#ffd66f}@media(max-width:600px){.clip{grid-template-columns:1fr auto}.clip button{grid-column:1/3}}</style></head><body><main>
<section class="hero"><div class="tag">TWITCH → YOUTUBE SHORTS</div><h1>ClipForge <span>Web</span></h1><p>Scan your Twitch clips, rank the strongest moments, and turn one into a vertical Short right in the browser.</p><div class="row"><a class="btn" href="/auth/twitch">Connect Twitch</a><button class="secondary" onclick="scan('demo')">Try demo</button><span class="pill" id="status">Checking…</span></div></section>
<div class="card" id="setup"><b>One-time Twitch setup</b><p>Register the callback below in your Twitch Developer Console, then add TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET to this website's Render environment variables.</p><code id="callback">loading…</code></div>
<div class="card"><div class="row"><b>Best clips</b><button onclick="scan('live')">Scan my Twitch</button><button class="secondary" onclick="scan('demo')">Demo scan</button></div><div id="clips" class="clips"><p>No clips scanned yet.</p></div></div>
<div class="card hidden" id="editor"><b>Short preview</b><p id="chosen"></p><div class="row"><button id="renderBtn" onclick="renderShort()">Generate 9:16 Short</button><span id="renderStatus" class="small"></span></div><br><video id="video" controls class="hidden"></video></div>
</main><script>
let clips=[], chosen=null;
async function api(url,opt={}){let r=await fetch(url,opt);let j=await r.json().catch(()=>({detail:r.statusText}));if(!r.ok)throw Error(j.detail||'Request failed');return j}
async function boot(){let s=await api('/api/status');status.textContent=s.connected?'Twitch connected ✓':'Twitch not connected';callback.textContent=s.callback;if(s.connected)setup.classList.add('hidden')}
async function scan(mode){clipsEl=document.getElementById('clips');clipsEl.innerHTML='<p>Scanning…</p>';try{let d=await api('/api/scan',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({mode})});clips=d.clips;clipsEl.innerHTML=clips.map((c,i)=>`<div class="clip"><div><b>${esc(c.title)}</b><div class="small">${c.view_count.toLocaleString()} views · ${c.duration.toFixed(1)}s · ${esc(c.reason)}</div></div><div class="score">${c.score}</div><button onclick="pick(${i})">Use clip</button></div>`).join('')||'<p>No clips found.</p>'}catch(e){clipsEl.innerHTML='<p class="warn">'+esc(e.message)+'</p>'}}
function esc(s){return String(s||'').replace(/[&<>\"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]))}
function pick(i){chosen=clips[i];editor.classList.remove('hidden');chosenEl=document.getElementById('chosen');chosenEl.textContent=chosen.title;editor.scrollIntoView({behavior:'smooth'})}
async function renderShort(){if(!chosen)return;renderStatus.textContent='Rendering… this can take ~30 seconds';video.classList.add('hidden');try{let d=await api('/api/render',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(chosen)});video.src=d.media_url+'?t='+Date.now();video.classList.remove('hidden');renderStatus.textContent='Ready ✓'}catch(e){renderStatus.textContent=e.message}}
boot();
</script></body></html>'''

def base_url(req:Request):
    return os.getenv('RENDER_EXTERNAL_URL','').rstrip('/') or str(req.base_url).rstrip('/')

def sid(req:Request):
    return req.cookies.get('cf_sid') or secrets.token_urlsafe(18)

def score(c):
    title=c.get('title','').lower(); words=['lol','lmao','wtf','fail','bro','insane','crazy','clutch','scream','rage','funny','no way','instant','regret']
    s=12+min(40,int(math.log10(max(c.get('view_count',0),1)+1)*10))+min(24,sum(w in title for w in words)*6)+max(0,int(20-abs(float(c.get('duration',0))-24)*.8))
    c['score']=min(99,s); c['reason']='viewer signal + short-friendly moment'; return c

DEMO=[
 {'id':'demo1','title':'BRO CELEBRATED WAY TOO EARLY 💀','view_count':18230,'duration':18.4},
 {'id':'demo2','title':'I KNEW HE WAS HIDING THERE!!','view_count':12410,'duration':22.0},
 {'id':'demo3','title':'the instant regret is crazy','view_count':7910,'duration':16.3},
 {'id':'demo4','title':'1 HP clutch no way','view_count':6550,'duration':31.1},
]

class Scan(BaseModel): mode:str='demo'
class ClipReq(BaseModel): id:str; title:str=''; view_count:int=0; duration:float=0; score:int=0; reason:str=''

@app.get('/',response_class=HTMLResponse)
def home(req:Request):
    r=HTMLResponse(HTML); r.set_cookie('cf_sid',sid(req),httponly=True,samesite='lax',max_age=2592000); return r

@app.get('/api/status')
def status(req:Request):
    s=sid(req); return {'connected':s in SESSIONS,'callback':base_url(req)+'/auth/twitch/callback'}

@app.get('/auth/twitch')
def twitch_auth(req:Request):
    cid=os.getenv('TWITCH_CLIENT_ID'); sec=os.getenv('TWITCH_CLIENT_SECRET')
    if not cid or not sec: return RedirectResponse('/?setup=1')
    s=sid(req); state=secrets.token_urlsafe(24); STATES[state]=(s,time.time())
    red=base_url(req)+'/auth/twitch/callback'
    q=urlencode({'client_id':cid,'redirect_uri':red,'response_type':'code','scope':'channel:manage:clips','state':state})
    r=RedirectResponse('https://id.twitch.tv/oauth2/authorize?'+q); r.set_cookie('cf_sid',s,httponly=True,samesite='lax',max_age=2592000); return r

@app.get('/auth/twitch/callback')
async def twitch_cb(req:Request,code:str,state:str):
    st=STATES.pop(state,None)
    if not st or time.time()-st[1]>900: raise HTTPException(400,'OAuth state expired')
    s=st[0]; red=base_url(req)+'/auth/twitch/callback'; cid=os.getenv('TWITCH_CLIENT_ID','')
    async with httpx.AsyncClient(timeout=30) as c:
        tr=await c.post('https://id.twitch.tv/oauth2/token',data={'client_id':cid,'client_secret':os.getenv('TWITCH_CLIENT_SECRET',''),'code':code,'grant_type':'authorization_code','redirect_uri':red})
        if tr.status_code>=400: raise HTTPException(502,'Twitch login failed: '+tr.text[:180])
        tok=tr.json(); ur=await c.get('https://api.twitch.tv/helix/users',headers={'Authorization':'Bearer '+tok['access_token'],'Client-Id':cid})
    user=ur.json().get('data',[{}])[0]; SESSIONS[s]={'token':tok['access_token'],'user':user}
    r=RedirectResponse('/'); r.set_cookie('cf_sid',s,httponly=True,samesite='lax',max_age=2592000); return r

@app.post('/api/scan')
async def scan(req:Request,p:Scan):
    if p.mode=='demo': return {'clips':sorted([score(dict(x)) for x in DEMO],key=lambda x:x['score'],reverse=True)}
    session=SESSIONS.get(sid(req));
    if not session: raise HTTPException(401,'Connect Twitch first')
    cid=os.getenv('TWITCH_CLIENT_ID',''); u=session['user']; headers={'Authorization':'Bearer '+session['token'],'Client-Id':cid}
    async with httpx.AsyncClient(timeout=30) as c:
        rr=await c.get('https://api.twitch.tv/helix/clips',headers=headers,params={'broadcaster_id':u['id'],'first':40})
    if rr.status_code>=400: raise HTTPException(502,'Twitch scan failed')
    clips=[]
    for x in rr.json().get('data',[]): clips.append(score({'id':x['id'],'title':x.get('title','Untitled'),'view_count':int(x.get('view_count',0)),'duration':float(x.get('duration',0))}))
    return {'clips':sorted(clips,key=lambda x:x['score'],reverse=True)}

@app.post('/api/render')
async def render(req:Request,p:ClipReq):
    try:
        import imageio_ffmpeg, subprocess
        ff=imageio_ffmpeg.get_ffmpeg_exe(); src=OUT/(p.id+'-src.mp4'); dest=OUT/(secrets.token_hex(8)+'.mp4')
        if p.id.startswith('demo'):
            cmd=[ff,'-y','-f','lavfi','-i','testsrc2=size=1280x720:rate=30','-f','lavfi','-i','sine=frequency=520:sample_rate=44100','-t','8','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(src)]
            subprocess.run(cmd,check=True,capture_output=True)
        else:
            session=SESSIONS.get(sid(req));
            if not session: raise HTTPException(401,'Connect Twitch first')
            cid=os.getenv('TWITCH_CLIENT_ID',''); uid=session['user']['id']; h={'Authorization':'Bearer '+session['token'],'Client-Id':cid}
            async with httpx.AsyncClient(timeout=60,follow_redirects=True) as c:
                dr=await c.get('https://api.twitch.tv/helix/clips/downloads',headers=h,params={'broadcaster_id':uid,'editor_id':uid,'clip_id':p.id})
                if dr.status_code>=400: raise HTTPException(502,'Twitch clip download failed: '+dr.text[:120])
                d=dr.json().get('data',[]); url=(d[0].get('portrait_download_url') or d[0].get('landscape_download_url')) if d else None
                if not url: raise HTTPException(502,'No clip download URL returned')
                vr=await c.get(url); src.write_bytes(vr.content)
        hook=re.sub(r"[^A-Za-z0-9 !?.,'-]",'',p.title.upper())[:55] or 'THIS GOT OUT OF HAND'
        filt="[0:v]split=2[b][f];[b]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=22:8[b2];[f]scale=1020:-2[f2];[b2][f2]overlay=(W-w)/2:(H-h)/2,drawbox=x=55:y=90:w=970:h=210:color=black@0.60:t=fill,drawtext=text='%s':fontsize=58:fontcolor=white:x=(w-text_w)/2:y=140:borderw=3:bordercolor=black[v]"%hook.replace("'","\\'").replace(':','\\:')
        cp=subprocess.run([ff,'-y','-i',str(src),'-filter_complex',filt,'-map','[v]','-map','0:a?','-t','59','-c:v','libx264','-preset','veryfast','-crf','22','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(dest)],capture_output=True,text=True)
        if cp.returncode: raise HTTPException(500,'Render failed: '+cp.stderr[-400:])
        return {'media_url':'/media/'+dest.name}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500,str(e))

@app.get('/media/{name}')
def media(name:str):
    p=OUT/Path(name).name
    if not p.exists(): raise HTTPException(404)
    return FileResponse(p,media_type='video/mp4')
