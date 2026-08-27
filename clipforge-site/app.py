import os, secrets, time, math, re, subprocess
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="ClipForge")
SESSIONS = {}
STATES = {}
OUT = Path("/tmp/clipforge")
OUT.mkdir(parents=True, exist_ok=True)

HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ClipForge</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#090a0f;color:#f7f7fb;font:15px system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1000px;margin:auto;padding:32px 18px 64px}
.hero{padding:54px 0 32px}
.tag{font-size:12px;font-weight:900;letter-spacing:.14em;color:#9f7aea}
h1{font-size:clamp(44px,9vw,82px);line-height:.94;margin:12px 0}
h1 span{color:#9b6cff}
p{color:#a5a9b8;line-height:1.6}
.card{margin:16px 0;padding:22px;border:1px solid #2b2f3d;border-radius:18px;background:#12141b}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.btn,button{border:0;border-radius:11px;padding:12px 16px;background:#835dff;color:white;font-weight:850;text-decoration:none;cursor:pointer}
.secondary{background:#242733}
.pill{border:1px solid #343948;border-radius:999px;padding:8px 11px;color:#adb2c2;font-size:12px}
code{display:block;padding:12px;background:#0c0e13;border:1px solid #292d3a;border-radius:9px;overflow:auto}
.clips{display:grid;gap:11px;margin-top:15px}
.clip{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;padding:15px;border:1px solid #2e3342;background:#191c25;border-radius:13px}
.score{font-size:25px;font-weight:900;color:#5ce6a5}
.small{font-size:12px;color:#9299aa}
.hidden{display:none}
.warn{color:#ffd274}
video{width:min(340px,100%);aspect-ratio:9/16;background:#000;border-radius:16px}
@media(max-width:640px){.clip{grid-template-columns:1fr auto}.clip button{grid-column:1/3}}
</style>
</head>
<body>
<main>
<section class="hero">
<div class="tag">TWITCH → YOUTUBE SHORTS</div>
<h1>ClipForge <span>Web</span></h1>
<p>Scan your Twitch clips, rank the strongest moments, and turn one into a vertical Short from one website.</p>
<div class="row">
<a class="btn" href="/auth/twitch">Connect Twitch</a>
<button class="secondary" onclick="scan('demo')">Try demo</button>
<span class="pill" id="status">Checking…</span>
</div>
</section>

<div class="card" id="setup">
<b>One-time Twitch setup</b>
<p>Add this exact callback URL to your Twitch Developer app, then add TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in Render.</p>
<code id="callback">Loading…</code>
</div>

<div class="card">
<div class="row">
<b>Best clips</b>
<button onclick="scan('live')">Scan my Twitch</button>
<button class="secondary" onclick="scan('demo')">Demo scan</button>
</div>
<div id="clips" class="clips"><p>No clips scanned yet.</p></div>
</div>

<div class="card hidden" id="editor">
<b>Short preview</b>
<p id="chosen"></p>
<div class="row">
<button onclick="renderShort()">Generate 9:16 Short</button>
<span class="small" id="renderStatus"></span>
</div>
<br>
<video id="video" controls class="hidden"></video>
</div>
</main>

<script>
let clips=[], chosen=null;
const $=id=>document.getElementById(id);
function esc(s){return String(s||'').replace(/[&<>\"]/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[m]))}
async function api(url,opt={}){
  const r=await fetch(url,opt);
  const j=await r.json().catch(()=>({detail:r.statusText||"Request failed"}));
  if(!r.ok) throw new Error(j.detail||"Request failed");
  return j;
}
async function boot(){
  try{
    const s=await api("/api/status");
    $("status").textContent=s.connected?"Twitch connected ✓":"Twitch not connected";
    $("callback").textContent=s.callback;
    if(s.connected)$("setup").classList.add("hidden");
  }catch(e){$("status").textContent="Server error";}
}
async function scan(mode){
  $("clips").innerHTML="<p>Scanning…</p>";
  try{
    const d=await api("/api/scan",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({mode})});
    clips=d.clips||[];
    $("clips").innerHTML=clips.map((c,i)=>`<div class="clip"><div><b>${esc(c.title)}</b><div class="small">${Number(c.view_count).toLocaleString()} views · ${Number(c.duration).toFixed(1)}s · ${esc(c.reason)}</div></div><div class="score">${c.score}</div><button onclick="pick(${i})">Use clip</button></div>`).join("")||"<p>No clips found.</p>";
  }catch(e){$("clips").innerHTML=`<p class="warn">${esc(e.message)}</p>`}
}
function pick(i){
  chosen=clips[i];
  $("editor").classList.remove("hidden");
  $("chosen").textContent=chosen.title;
  $("editor").scrollIntoView({behavior:"smooth"});
}
async function renderShort(){
  if(!chosen)return;
  $("renderStatus").textContent="Rendering…";
  $("video").classList.add("hidden");
  try{
    const d=await api("/api/render",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(chosen)});
    $("video").src=d.media_url+"?t="+Date.now();
    $("video").classList.remove("hidden");
    $("renderStatus").textContent="Ready ✓";
  }catch(e){$("renderStatus").textContent=e.message}
}
boot();
</script>
</body>
</html>"""

def base_url(req: Request) -> str:
    return os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/") or str(req.base_url).rstrip("/")

def sid(req: Request) -> str:
    return req.cookies.get("cf_sid") or secrets.token_urlsafe(18)

def score_clip(c: dict) -> dict:
    title = c.get("title", "").lower()
    words = ["lol","lmao","wtf","fail","bro","insane","crazy","clutch","scream","rage","funny","no way","instant","regret"]
    views = max(int(c.get("view_count", 0)), 0)
    duration = float(c.get("duration", 0) or 0)
    points = 12 + min(40, int(math.log10(views + 1) * 10))
    points += min(24, sum(w in title for w in words) * 6)
    points += max(0, int(20 - abs(duration - 24) * 0.8))
    c["score"] = min(99, points)
    c["reason"] = "viewer signal + short-friendly moment"
    return c

DEMO = [
    {"id":"demo1","title":"BRO CELEBRATED WAY TOO EARLY 💀","view_count":18230,"duration":18.4},
    {"id":"demo2","title":"I KNEW HE WAS HIDING THERE!!","view_count":12410,"duration":22.0},
    {"id":"demo3","title":"the instant regret is crazy","view_count":7910,"duration":16.3},
    {"id":"demo4","title":"1 HP clutch no way","view_count":6550,"duration":31.1},
]

class ScanReq(BaseModel):
    mode: str = "demo"

class ClipReq(BaseModel):
    id: str
    title: str = ""
    view_count: int = 0
    duration: float = 0
    score: int = 0
    reason: str = ""

@app.api_route("/", methods=["GET","HEAD"], response_class=HTMLResponse)
async def home(req: Request):
    r = HTMLResponse(content=HTML, status_code=200)
    r.set_cookie("cf_sid", sid(req), httponly=True, samesite="lax", max_age=2592000)
    return r

@app.get("/health")
async def health():
    return {"ok": True, "app": "ClipForge"}

@app.get("/api/status")
async def status(req: Request):
    s = sid(req)
    return {"connected": s in SESSIONS, "callback": base_url(req) + "/auth/twitch/callback"}

@app.get("/auth/twitch")
async def twitch_auth(req: Request):
    cid = os.getenv("TWITCH_CLIENT_ID")
    secret = os.getenv("TWITCH_CLIENT_SECRET")
    if not cid or not secret:
        return RedirectResponse("/?setup=1")
    s = sid(req)
    state = secrets.token_urlsafe(24)
    STATES[state] = (s, time.time())
    redirect_uri = base_url(req) + "/auth/twitch/callback"
    q = urlencode({
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "channel:manage:clips",
        "state": state,
    })
    r = RedirectResponse("https://id.twitch.tv/oauth2/authorize?" + q)
    r.set_cookie("cf_sid", s, httponly=True, samesite="lax", max_age=2592000)
    return r

@app.get("/auth/twitch/callback")
async def twitch_callback(req: Request, code: str, state: str):
    saved = STATES.pop(state, None)
    if not saved or time.time() - saved[1] > 900:
        raise HTTPException(400, "OAuth state expired")
    s = saved[0]
    cid = os.getenv("TWITCH_CLIENT_ID", "")
    redirect_uri = base_url(req) + "/auth/twitch/callback"
    async with httpx.AsyncClient(timeout=30) as client:
        token_response = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": cid,
                "client_secret": os.getenv("TWITCH_CLIENT_SECRET", ""),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        if token_response.status_code >= 400:
            raise HTTPException(502, "Twitch login failed: " + token_response.text[:180])
        token = token_response.json()
        user_response = await client.get(
            "https://api.twitch.tv/helix/users",
            headers={"Authorization":"Bearer " + token["access_token"], "Client-Id":cid},
        )
    users = user_response.json().get("data", [])
    if not users:
        raise HTTPException(502, "Could not read Twitch profile")
    SESSIONS[s] = {"token": token["access_token"], "user": users[0]}
    r = RedirectResponse("/")
    r.set_cookie("cf_sid", s, httponly=True, samesite="lax", max_age=2592000)
    return r

@app.post("/api/scan")
async def scan(req: Request, payload: ScanReq):
    if payload.mode == "demo":
        clips = [score_clip(dict(x)) for x in DEMO]
        return {"clips": sorted(clips, key=lambda x:x["score"], reverse=True)}
    session = SESSIONS.get(sid(req))
    if not session:
        raise HTTPException(401, "Connect Twitch first")
    cid = os.getenv("TWITCH_CLIENT_ID", "")
    user = session["user"]
    headers = {"Authorization":"Bearer " + session["token"], "Client-Id":cid}
    async with httpx.AsyncClient(timeout=30) as client:
        rr = await client.get(
            "https://api.twitch.tv/helix/clips",
            headers=headers,
            params={"broadcaster_id": user["id"], "first": 40},
        )
    if rr.status_code >= 400:
        raise HTTPException(502, "Twitch scan failed: " + rr.text[:140])
    clips = [
        score_clip({
            "id": x["id"],
            "title": x.get("title", "Untitled"),
            "view_count": int(x.get("view_count", 0)),
            "duration": float(x.get("duration", 0)),
        })
        for x in rr.json().get("data", [])
    ]
    return {"clips": sorted(clips, key=lambda x:x["score"], reverse=True)}

@app.post("/api/render")
async def render(req: Request, payload: ClipReq):
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        src = OUT / f"{payload.id}-src.mp4"
        dest = OUT / f"{secrets.token_hex(8)}.mp4"

        if payload.id.startswith("demo"):
            cp = subprocess.run([
                ffmpeg,"-y","-f","lavfi","-i","testsrc2=size=1280x720:rate=30",
                "-f","lavfi","-i","sine=frequency=520:sample_rate=44100",
                "-t","8","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac",str(src)
            ], capture_output=True, text=True)
            if cp.returncode:
                raise HTTPException(500, "Demo source render failed")
        else:
            session = SESSIONS.get(sid(req))
            if not session:
                raise HTTPException(401, "Connect Twitch first")
            cid = os.getenv("TWITCH_CLIENT_ID", "")
            uid = session["user"]["id"]
            headers = {"Authorization":"Bearer " + session["token"], "Client-Id":cid}
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                dr = await client.get(
                    "https://api.twitch.tv/helix/clips/downloads",
                    headers=headers,
                    params={"broadcaster_id":uid, "editor_id":uid, "clip_id":payload.id},
                )
                if dr.status_code >= 400:
                    raise HTTPException(502, "Twitch clip download failed: " + dr.text[:140])
                data = dr.json().get("data", [])
                url = (data[0].get("portrait_download_url") or data[0].get("landscape_download_url")) if data else None
                if not url:
                    raise HTTPException(502, "No clip download URL returned")
                vr = await client.get(url)
                if vr.status_code >= 400:
                    raise HTTPException(502, "Could not download Twitch clip")
                src.write_bytes(vr.content)

        hook = re.sub(r"[^A-Za-z0-9 !?.,'-]", "", payload.title.upper())[:55] or "THIS GOT OUT OF HAND"
        hook = hook.replace("\\", "").replace("'", r"\'").replace(":", r"\:")
        filt = (
            "[0:v]split=2[b][f];"
            "[b]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=22:8[b2];"
            "[f]scale=1020:-2[f2];"
            "[b2][f2]overlay=(W-w)/2:(H-h)/2,"
            "drawbox=x=55:y=90:w=970:h=210:color=black@0.60:t=fill,"
            f"drawtext=text='{hook}':fontsize=58:fontcolor=white:x=(w-text_w)/2:y=140:borderw=3:bordercolor=black[v]"
        )
        cp = subprocess.run([
            ffmpeg,"-y","-i",str(src),"-filter_complex",filt,
            "-map","[v]","-map","0:a?","-t","59",
            "-c:v","libx264","-preset","veryfast","-crf","22","-pix_fmt","yuv420p",
            "-c:a","aac","-movflags","+faststart",str(dest)
        ], capture_output=True, text=True)
        if cp.returncode:
            raise HTTPException(500, "Render failed: " + cp.stderr[-400:])
        return {"media_url": "/media/" + dest.name}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))

@app.get("/media/{name}")
async def media(name: str):
    p = OUT / Path(name).name
    if not p.exists():
        raise HTTPException(404, "Video not found")
    return FileResponse(p, media_type="video/mp4")
