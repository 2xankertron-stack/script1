import os
import secrets
import time
import math
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from pydantic import BaseModel, Field
from studio_ui import HTML

app = FastAPI(title="ClipForge")
SESSIONS = {}
STATES = {}
APP_TOKEN = {"token": "", "expires_at": 0.0}
OUT = Path("/tmp/clipforge")
OUT.mkdir(parents=True, exist_ok=True)

def base_url(req: Request) -> str:
    return os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/") or str(req.base_url).rstrip("/")

def sid(req: Request) -> str:
    return req.cookies.get("cf_sid") or secrets.token_urlsafe(18)

def score_clip(c: dict) -> dict:
    title = c.get("title", "").lower()
    words = ["lol", "lmao", "wtf", "fail", "bro", "insane", "crazy", "clutch", "scream", "rage", "funny", "no way", "instant", "regret"]
    views = max(int(c.get("view_count", 0)), 0)
    duration = float(c.get("duration", 0) or 0)
    points = 12 + min(40, int(math.log10(views + 1) * 10))
    points += min(24, sum(w in title for w in words) * 6)
    points += max(0, int(20 - abs(duration - 24) * 0.8))
    c["score"] = min(99, points)
    c["reason"] = "viewer signal + short-friendly moment"
    return c

async def get_app_token() -> str:
    now = time.time()
    if APP_TOKEN["token"] and APP_TOKEN["expires_at"] > now + 60:
        return APP_TOKEN["token"]
    cid = os.getenv("TWITCH_CLIENT_ID")
    secret = os.getenv("TWITCH_CLIENT_SECRET")
    if not cid or not secret:
        raise HTTPException(503, "Add TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in Render first")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post("https://id.twitch.tv/oauth2/token", data={"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
    if r.status_code >= 400:
        raise HTTPException(502, "Could not authenticate ClipForge with Twitch")
    data = r.json()
    APP_TOKEN["token"] = data["access_token"]
    APP_TOKEN["expires_at"] = now + int(data.get("expires_in", 3600))
    return APP_TOKEN["token"]

DEMO = [
    {"id": "demo1", "title": "BRO CELEBRATED WAY TOO EARLY 💀", "view_count": 18230, "duration": 18.4, "broadcaster_name": "DemoStreamer", "broadcaster_id": "demo"},
    {"id": "demo2", "title": "I KNEW HE WAS HIDING THERE!!", "view_count": 12410, "duration": 22.0, "broadcaster_name": "DemoStreamer", "broadcaster_id": "demo"},
    {"id": "demo3", "title": "the instant regret is crazy", "view_count": 7910, "duration": 16.3, "broadcaster_name": "DemoStreamer", "broadcaster_id": "demo"},
    {"id": "demo4", "title": "1 HP clutch no way", "view_count": 6550, "duration": 31.1, "broadcaster_name": "DemoStreamer", "broadcaster_id": "demo"},
]

class ScanReq(BaseModel):
    mode: str = "demo"

class ScoutReq(BaseModel):
    channels: str = Field(min_length=1, max_length=500)

class ClipEdit(BaseModel):
    id: str
    title: str = ""
    view_count: int = 0
    duration: float = 0
    score: int = 0
    reason: str = ""
    broadcaster_id: str = ""
    broadcaster_name: str = ""
    url: str = ""
    render_hint: str = ""
    trim_start: float = 0
    trim_end: float = 20
    overlay: str = ""

class ProjectReq(BaseModel):
    hook: str = Field(default="", max_length=80)
    items: list[ClipEdit] = Field(min_length=1, max_length=10)

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
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
    q = urlencode({"client_id": cid, "redirect_uri": redirect_uri, "response_type": "code", "scope": "channel:manage:clips editor:manage:clips", "state": state})
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
        token_response = await client.post("https://id.twitch.tv/oauth2/token", data={"client_id": cid, "client_secret": os.getenv("TWITCH_CLIENT_SECRET", ""), "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri})
        if token_response.status_code >= 400:
            raise HTTPException(502, "Twitch login failed: " + token_response.text[:180])
        token = token_response.json()
        user_response = await client.get("https://api.twitch.tv/helix/users", headers={"Authorization": "Bearer " + token["access_token"], "Client-Id": cid})
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
        return {"clips": sorted([score_clip(dict(x)) for x in DEMO], key=lambda x: x["score"], reverse=True)}
    session = SESSIONS.get(sid(req))
    if not session:
        raise HTTPException(401, "Connect Twitch first")
    cid = os.getenv("TWITCH_CLIENT_ID", "")
    user = session["user"]
    headers = {"Authorization": "Bearer " + session["token"], "Client-Id": cid}
    async with httpx.AsyncClient(timeout=30) as client:
        rr = await client.get("https://api.twitch.tv/helix/clips", headers=headers, params={"broadcaster_id": user["id"], "first": 40})
    if rr.status_code >= 400:
        raise HTTPException(502, "Twitch scan failed: " + rr.text[:140])
    clips = []
    for x in rr.json().get("data", []):
        clips.append(score_clip({"id": x["id"], "title": x.get("title", "Untitled"), "view_count": int(x.get("view_count", 0)), "duration": float(x.get("duration", 0)), "broadcaster_id": x.get("broadcaster_id", user["id"]), "broadcaster_name": x.get("broadcaster_name", user.get("display_name", "")), "url": x.get("url", "")}))
    return {"clips": sorted(clips, key=lambda x: x["score"], reverse=True)}

@app.post("/api/scout")
async def scout(payload: ScoutReq):
    names = []
    for name in re.split(r"[\s,]+", payload.channels.strip()):
        cleaned = re.sub(r"[^A-Za-z0-9_]", "", name).lower()
        if cleaned and cleaned not in names:
            names.append(cleaned)
    names = names[:10]
    if not names:
        raise HTTPException(400, "Enter at least one valid Twitch username")
    token = await get_app_token()
    cid = os.getenv("TWITCH_CLIENT_ID", "")
    headers = {"Authorization": "Bearer " + token, "Client-Id": cid}
    async with httpx.AsyncClient(timeout=30) as client:
        users_resp = await client.get("https://api.twitch.tv/helix/users", headers=headers, params=[("login", n) for n in names])
        if users_resp.status_code >= 400:
            raise HTTPException(502, "Could not look up Twitch channels")
        users = users_resp.json().get("data", [])
        all_clips = []
        started_at = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat().replace("+00:00", "Z")
        for u in users:
            rr = await client.get("https://api.twitch.tv/helix/clips", headers=headers, params={"broadcaster_id": u["id"], "first": 40, "started_at": started_at})
            if rr.status_code >= 400:
                continue
            for x in rr.json().get("data", []):
                all_clips.append(score_clip({"id": x["id"], "title": x.get("title", "Untitled"), "view_count": int(x.get("view_count", 0)), "duration": float(x.get("duration", 0)), "broadcaster_id": x.get("broadcaster_id", u["id"]), "broadcaster_name": x.get("broadcaster_name", u.get("display_name", "")), "url": x.get("url", ""), "render_hint": "Rendering needs broadcaster/editor permission."}))
    all_clips.sort(key=lambda x: x["score"], reverse=True)
    return {"clips": all_clips[:80], "channels_found": [u.get("display_name") for u in users]}

def drawtext_escape(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9 !?.,'\-]", "", text.upper())[:70]
    return text.replace("\\", "").replace("'", r"\'").replace(":", r"\:")

async def get_clip_source(req: Request, clip: ClipEdit, ffmpeg: str) -> Path:
    src = OUT / f"{clip.id}-{secrets.token_hex(4)}-src.mp4"
    if clip.id.startswith("demo"):
        cp = subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", "sine=frequency=520:sample_rate=44100", "-t", str(max(8, min(35, clip.duration or 20))), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], capture_output=True, text=True)
        if cp.returncode:
            raise HTTPException(500, "Demo source render failed")
        return src
    session = SESSIONS.get(sid(req))
    if not session:
        raise HTTPException(401, "Connect Twitch before rendering real clips")
    cid = os.getenv("TWITCH_CLIENT_ID", "")
    editor_id = session["user"]["id"]
    broadcaster_id = clip.broadcaster_id or editor_id
    headers = {"Authorization": "Bearer " + session["token"], "Client-Id": cid}
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        dr = await client.get("https://api.twitch.tv/helix/clips/downloads", headers=headers, params={"broadcaster_id": broadcaster_id, "editor_id": editor_id, "clip_id": clip.id})
        if dr.status_code >= 400:
            raise HTTPException(403, f"Can't download {clip.broadcaster_name or 'this channel'}'s clip. Your Twitch account must be that broadcaster or an authorized editor.")
        data = dr.json().get("data", [])
        url = (data[0].get("portrait_download_url") or data[0].get("landscape_download_url")) if data else None
        if not url:
            raise HTTPException(502, "Twitch did not return a clip download URL")
        vr = await client.get(url)
        if vr.status_code >= 400:
            raise HTTPException(502, "Could not download clip video")
        src.write_bytes(vr.content)
    return src

@app.post("/api/project/render")
async def render_project(req: Request, payload: ProjectReq):
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        project_id = secrets.token_hex(8)
        segments = []
        total = 0.0
        for i, item in enumerate(payload.items):
            start = max(0.0, float(item.trim_start))
            source_duration = max(0.1, float(item.duration or item.trim_end or 20))
            end = min(source_duration, max(start + 0.1, float(item.trim_end)))
            duration = min(end - start, max(0.1, 59.0 - total))
            if duration <= 0.09:
                break
            src = await get_clip_source(req, item, ffmpeg)
            seg = OUT / f"{project_id}-seg-{i}.mp4"
            overlay = drawtext_escape(item.overlay or (payload.hook if i == 0 else ""))
            base = "[0:v]split=2[b][f];[b]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=22:8[b2];[f]scale=1020:-2[f2];[b2][f2]overlay=(W-w)/2:(H-h)/2"
            if overlay:
                base += ",drawbox=x=55:y=90:w=970:h=210:color=black@0.60:t=fill,drawtext=text='%s':fontsize=58:fontcolor=white:x=(w-text_w)/2:y=140:borderw=3:bordercolor=black" % overlay
            filt = base + "[v]"
            cp = subprocess.run([ffmpeg, "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}", "-filter_complex", filt, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", str(seg)], capture_output=True, text=True)
            if cp.returncode:
                raise HTTPException(500, "Clip render failed: " + cp.stderr[-300:])
            segments.append(seg)
            total += duration
            if total >= 58.9:
                break
        if not segments:
            raise HTTPException(400, "No usable clip duration selected")
        concat_file = OUT / f"{project_id}.txt"
        concat_file.write_text("".join(f"file '{p.as_posix()}'\n" for p in segments), encoding="utf-8")
        dest = OUT / f"{project_id}.mp4"
        cp = subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", "-movflags", "+faststart", str(dest)], capture_output=True, text=True)
        if cp.returncode:
            cp = subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac", "-movflags", "+faststart", str(dest)], capture_output=True, text=True)
        if cp.returncode:
            raise HTTPException(500, "Final export failed: " + cp.stderr[-300:])
        return {"media_url": "/media/" + dest.name, "download_url": "/download/" + dest.name, "duration": min(total, 59.0), "clips_used": len(segments)}
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

@app.get("/download/{name}")
async def download(name: str):
    p = OUT / Path(name).name
    if not p.exists():
        raise HTTPException(404, "Video not found")
    return FileResponse(p, media_type="video/mp4", filename="clipforge-short.mp4")
