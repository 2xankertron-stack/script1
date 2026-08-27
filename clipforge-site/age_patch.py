import re
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

import studio_app


class AgeScanReq(BaseModel):
    mode: str = "live"
    age: str = "7d"


class AgeScoutReq(BaseModel):
    channels: str = Field(min_length=1, max_length=500)
    age: str = "7d"


def _age_key(value: str) -> str:
    value = (value or "7d").lower().strip()
    return value if value in {"24h", "7d", "30d", "all"} else "7d"


def _age_params(value: str) -> dict:
    age = _age_key(value)
    if age == "all":
        return {}
    now = datetime.now(timezone.utc)
    if age == "24h":
        start = now - timedelta(hours=24)
    elif age == "30d":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=7)
    return {
        "started_at": start.isoformat().replace("+00:00", "Z"),
        "ended_at": now.isoformat().replace("+00:00", "Z"),
    }


def _clip_from_twitch(x: dict, fallback_user: dict | None = None) -> dict:
    fallback_user = fallback_user or {}
    return studio_app.score_clip({
        "id": x["id"],
        "title": x.get("title", "Untitled"),
        "view_count": int(x.get("view_count", 0)),
        "duration": float(x.get("duration", 0)),
        "broadcaster_id": x.get("broadcaster_id", fallback_user.get("id", "")),
        "broadcaster_name": x.get("broadcaster_name", fallback_user.get("display_name", "")),
        "url": x.get("url", ""),
        "thumbnail_url": x.get("thumbnail_url", ""),
        "created_at": x.get("created_at", ""),
    })


def register_age_routes(app):
    @app.post("/api/scan-age")
    async def scan_age(req: Request, payload: AgeScanReq):
        age = _age_key(payload.age)
        if payload.mode == "demo":
            return {
                "clips": sorted([studio_app.score_clip(dict(x)) for x in studio_app.DEMO], key=lambda x: x["score"], reverse=True),
                "age": age,
            }
        session = studio_app.SESSIONS.get(studio_app.sid(req))
        if not session:
            raise HTTPException(401, "Connect Twitch first")
        cid = studio_app.os.getenv("TWITCH_CLIENT_ID", "")
        user = session["user"]
        headers = {"Authorization": "Bearer " + session["token"], "Client-Id": cid}
        params = {"broadcaster_id": user["id"], "first": 100, **_age_params(age)}
        async with httpx.AsyncClient(timeout=30) as client:
            rr = await client.get("https://api.twitch.tv/helix/clips", headers=headers, params=params)
        if rr.status_code >= 400:
            raise HTTPException(502, "Twitch scan failed: " + rr.text[:160])
        clips = [_clip_from_twitch(x, user) for x in rr.json().get("data", [])]
        clips.sort(key=lambda x: x["score"], reverse=True)
        return {"clips": clips, "age": age}

    @app.post("/api/scout-age")
    async def scout_age(payload: AgeScoutReq):
        age = _age_key(payload.age)
        names = []
        for name in re.split(r"[\s,]+", payload.channels.strip()):
            cleaned = re.sub(r"[^A-Za-z0-9_]", "", name).lower()
            if cleaned and cleaned not in names:
                names.append(cleaned)
        names = names[:10]
        if not names:
            raise HTTPException(400, "Enter at least one valid Twitch username")

        token = await studio_app.get_app_token()
        cid = studio_app.os.getenv("TWITCH_CLIENT_ID", "")
        headers = {"Authorization": "Bearer " + token, "Client-Id": cid}
        async with httpx.AsyncClient(timeout=30) as client:
            users_resp = await client.get(
                "https://api.twitch.tv/helix/users",
                headers=headers,
                params=[("login", n) for n in names],
            )
            if users_resp.status_code >= 400:
                raise HTTPException(502, "Could not look up Twitch channels")
            users = users_resp.json().get("data", [])
            all_clips = []
            for user in users:
                params = {"broadcaster_id": user["id"], "first": 100, **_age_params(age)}
                rr = await client.get("https://api.twitch.tv/helix/clips", headers=headers, params=params)
                if rr.status_code >= 400:
                    continue
                for x in rr.json().get("data", []):
                    clip = _clip_from_twitch(x, user)
                    clip["render_hint"] = "Preview works publicly. MP4 export needs broadcaster/editor permission."
                    all_clips.append(clip)

        all_clips.sort(key=lambda x: x["score"], reverse=True)
        return {
            "clips": all_clips[:100],
            "channels_found": [u.get("display_name") for u in users],
            "age": age,
        }


def apply_age_patch(html: str) -> str:
    style_anchor = ".secondary{background:#242733}.ghost{background:transparent;border:1px solid #3a4050}.danger{background:#612a34}.pill{border:1px solid #343948;border-radius:999px;padding:8px 11px;color:#adb2c2;font-size:12px}"
    style_extra = style_anchor + "\n.ageBar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 14px;padding:13px 15px;background:#10121a;border:1px solid #2b2f3d;border-radius:14px}.ageBar label{font-weight:900}.ageSelect{appearance:none;background:#242733;color:#fff;border:1px solid #484e60;border-radius:10px;padding:10px 34px 10px 12px;font:inherit;font-weight:850;cursor:pointer;background-image:linear-gradient(45deg,transparent 50%,#b8a6ff 50%),linear-gradient(135deg,#b8a6ff 50%,transparent 50%);background-position:calc(100% - 15px) 50%,calc(100% - 10px) 50%;background-size:5px 5px,5px 5px;background-repeat:no-repeat}.ageSelect option{background:#2a2d38;color:#fff}.ageHint{color:#8f96a8;font-size:12px}"
    html = html.replace(style_anchor, style_extra)

    panel_anchor = '<section id="clipsPanel" class="tabPanel active">'
    age_bar = panel_anchor + '\n<div class="ageBar"><label for="clipAge">Filter by</label><select id="clipAge" class="ageSelect" onchange="updateAgeLabel()"><option value="24h">Top 24H</option><option value="7d" selected>Top 7D</option><option value="30d">Top 30D</option><option value="all">Top ALL</option></select><span class="ageHint">Showing <b id="ageLabel">Top 7D</b> clips</span></div>'
    html = html.replace(panel_anchor, age_bar)

    old_scan = "async function scanMine(mode){showTab('clips');$('clips').innerHTML='<p>Scanning…</p>';try{const d=await api('/api/scan',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({mode})});clips=d.clips||[];$('clips').innerHTML=clips.map((c,i)=>card(c,i,'mine')).join('')||'<p>No clips found.</p>'}catch(e){$('clips').innerHTML=`<p class=\"warn\">${esc(e.message)}</p>`}}"
    new_scan = "async function scanMine(mode){showTab('clips');$('clips').innerHTML='<p>Scanning…</p>';try{const age=$('clipAge')?$('clipAge').value:'7d';const endpoint=mode==='demo'?'/api/scan':'/api/scan-age';const payload=mode==='demo'?{mode}:{mode,age};const d=await api(endpoint,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});clips=d.clips||[];$('clips').innerHTML=clips.map((c,i)=>card(c,i,'mine')).join('')||'<p>No clips found in this age range.</p>'}catch(e){$('clips').innerHTML=`<p class=\"warn\">${esc(e.message)}</p>`}}"
    html = html.replace(old_scan, new_scan)

    old_scout_call = "const d=await api('/api/scout',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({channels:raw})});"
    new_scout_call = "const age=$('clipAge')?$('clipAge').value:'7d';const d=await api('/api/scout-age',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({channels:raw,age})});"
    html = html.replace(old_scout_call, new_scout_call)

    script_anchor = "function showTab(name){"
    helper = "function updateAgeLabel(){const s=$('clipAge');if(!s)return;$('ageLabel').textContent=s.options[s.selectedIndex].text;}\n" + script_anchor
    html = html.replace(script_anchor, helper, 1)
    return html
