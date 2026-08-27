import re
import secrets
import subprocess
from pathlib import Path

from fastapi import UploadFile, File, Form, HTTPException

AI_OUT = Path('/tmp/clipforge-ai')
AI_OUT.mkdir(parents=True, exist_ok=True)


def _escape_drawtext(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9 !?.,'\-]", "", (text or '').upper())[:72]
    return text.replace('\\', '').replace("'", r"\'").replace(':', r"\:")


def apply_ai_editor_patch(html: str) -> str:
    # Add a third top-level tab.
    html = html.replace(
        '<button id="editorTab" class="tab" onclick="showTab(\'editor\')">Short Editor <span id="tabSelectedCount" class="tabBadge hidden">0</span></button>',
        '<button id="editorTab" class="tab" onclick="showTab(\'editor\')">Short Editor <span id="tabSelectedCount" class="tabBadge hidden">0</span></button>\n<button id="aiTab" class="tab" onclick="showAiTab()">✨ AI Editor</button>'
    )

    panel = r'''
<section id="aiPanel" class="tabPanel">
  <div class="card aiEditorCard">
    <div class="editorHero">
      <div>
        <h2>✨ AI Editor</h2>
        <p>Upload the clips you want to use and ClipForge will automatically turn them into a fast vertical TikTok-style edit.</p>
      </div>
      <span class="pill">Auto edit</span>
    </div>

    <div class="aiGrid" style="margin-top:18px">
      <div>
        <label class="aiDrop" for="aiFiles">
          <input id="aiFiles" type="file" accept="video/*" multiple hidden onchange="aiFilesChanged()">
          <div class="aiDropIcon">＋</div>
          <b>Select video files</b>
          <span>MP4, MOV, WEBM or MKV · up to 8 clips</span>
        </label>
        <div id="aiFileList" class="aiFileList"><div class="small">No files selected yet.</div></div>

        <div class="aiOptions">
          <label>Editing style
            <select id="aiStyle">
              <option value="viral">🔥 Viral / fast cuts</option>
              <option value="meme">💀 Meme energy</option>
              <option value="clean">✨ Clean creator</option>
              <option value="cinematic">🎬 Cinematic</option>
            </select>
          </label>
          <label>Target length
            <select id="aiLength">
              <option value="20">~20 sec</option>
              <option value="30" selected>~30 sec</option>
              <option value="45">~45 sec</option>
              <option value="58">~58 sec</option>
            </select>
          </label>
        </div>

        <label class="aiLabel">Opening hook
          <input id="aiHook" type="text" maxlength="72" placeholder="e.g. THIS GOT OUT OF HAND FAST 💀">
        </label>

        <div class="row" style="margin-top:15px">
          <button id="aiMakeBtn" onclick="makeAiTikTok()">✨ Make creative TikTok</button>
          <span id="aiStatus" class="small"></span>
        </div>
      </div>

      <aside class="aiPreviewWrap">
        <div class="previewLabel"><b>AI result</b><span id="aiResultBadge" class="pill">Waiting</span></div>
        <div class="aiPhone">
          <video id="aiResultVideo" controls playsinline></video>
          <div id="aiPlaceholder" class="aiPlaceholder"><span>✨</span><b>Your AI edit will appear here</b><small>Upload clips and press Make creative TikTok</small></div>
        </div>
        <a id="aiDownload" class="btn download hidden" href="#" download="clipforge-ai-tiktok.mp4">Download TikTok MP4</a>
      </aside>
    </div>
  </div>
</section>
'''
    html = html.replace('</main><script>', panel + '\n</main><script>')

    css = r'''
<style>
.aiGrid{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:24px;align-items:start}.aiDrop{min-height:180px;border:1px dashed #555c70;border-radius:18px;background:#0e1016;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;cursor:pointer;text-align:center;padding:24px}.aiDrop:hover{border-color:#835dff;background:#12131b}.aiDropIcon{width:48px;height:48px;border-radius:14px;background:#835dff22;border:1px solid #835dff66;color:#bca8ff;font-size:30px;display:grid;place-items:center}.aiDrop span{font-size:12px;color:#8f95a6}.aiFileList{display:grid;gap:7px;margin:12px 0}.aiFile{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid #303545;background:#171a22;border-radius:11px}.aiFile b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;font-size:13px}.aiFile span{font-size:11px;color:#9299aa}.aiOptions{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:15px 0}.aiOptions label,.aiLabel{font-size:12px;color:#a6acbc;display:block}.aiOptions select,.aiLabel input{width:100%;margin-top:6px;background:#0d0f15;color:#fff;border:1px solid #333847;border-radius:10px;padding:11px 12px;font:inherit}.aiPreviewWrap{position:sticky;top:90px}.aiPhone{width:300px;max-width:100%;aspect-ratio:9/16;border-radius:32px;border:7px solid #06070a;background:#000;overflow:hidden;position:relative;margin:auto;box-shadow:0 22px 60px #0008}.aiPhone video{width:100%;height:100%;object-fit:contain;background:#000}.aiPlaceholder{position:absolute;inset:0;background:radial-gradient(circle at 50% 35%,#352866,#12131b 48%,#050505);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:28px;color:#fff}.aiPlaceholder span{font-size:44px}.aiPlaceholder b{margin-top:10px}.aiPlaceholder small{margin-top:7px;color:#9299aa;line-height:1.45}.aiPreviewWrap .download{width:300px;max-width:100%;text-align:center;margin:12px auto 0;display:block}@media(max-width:900px){.aiGrid{grid-template-columns:1fr}.aiPreviewWrap{position:relative;top:auto;order:-1}}@media(max-width:600px){.aiOptions{grid-template-columns:1fr}}
</style>
'''
    html = html.replace('</head>', css + '</head>')

    js = r'''
<script>
(function(){
  window.showAiTab=function(){
    const cp=document.getElementById('clipsPanel'),ep=document.getElementById('editorPanel'),ap=document.getElementById('aiPanel');
    if(cp)cp.classList.remove('active'); if(ep)ep.classList.remove('active'); if(ap)ap.classList.add('active');
    const ct=document.getElementById('clipsTab'),et=document.getElementById('editorTab'),at=document.getElementById('aiTab');
    if(ct)ct.classList.remove('active'); if(et)et.classList.remove('active'); if(at)at.classList.add('active');
    window.scrollTo({top:0,behavior:'smooth'});
  };
  document.addEventListener('click',function(e){
    if(e.target && (e.target.id==='clipsTab'||e.target.id==='editorTab')){
      const ap=document.getElementById('aiPanel'),at=document.getElementById('aiTab');
      if(ap)ap.classList.remove('active'); if(at)at.classList.remove('active');
    }
  },true);
  window.aiFilesChanged=function(){
    const input=document.getElementById('aiFiles'),list=document.getElementById('aiFileList');
    const files=Array.from(input.files||[]).slice(0,8);
    if(!files.length){list.innerHTML='<div class="small">No files selected yet.</div>';return;}
    list.innerHTML=files.map((f,i)=>'<div class="aiFile"><span>🎞️</span><b>'+esc(f.name)+'</b><span>'+((f.size/1024/1024).toFixed(1))+' MB</span></div>').join('');
  };
  window.makeAiTikTok=async function(){
    const input=document.getElementById('aiFiles'),files=Array.from(input.files||[]).slice(0,8),status=document.getElementById('aiStatus'),btn=document.getElementById('aiMakeBtn');
    if(!files.length){status.textContent='Select at least one video file.';return;}
    const form=new FormData(); files.forEach(f=>form.append('files',f));
    form.append('style',document.getElementById('aiStyle').value);
    form.append('target_length',document.getElementById('aiLength').value);
    form.append('hook',document.getElementById('aiHook').value.trim());
    btn.disabled=true;btn.textContent='Creating edit…';status.textContent='Uploading and auto-editing your clips…';
    try{
      const r=await fetch('/api/ai-editor/render',{method:'POST',body:form});
      const d=await r.json().catch(()=>({detail:'Render failed'}));
      if(!r.ok)throw new Error(d.detail||'Render failed');
      const v=document.getElementById('aiResultVideo'),ph=document.getElementById('aiPlaceholder'),dl=document.getElementById('aiDownload');
      v.src=d.media_url+'?t='+Date.now(); ph.classList.add('hidden'); dl.href=d.download_url; dl.classList.remove('hidden');
      document.getElementById('aiResultBadge').textContent='Ready · '+d.duration.toFixed(1)+'s';
      status.textContent='Done ✓ '+d.clips_used+' clips used';
      v.load();
    }catch(e){status.textContent=e.message;document.getElementById('aiResultBadge').textContent='Error';}
    finally{btn.disabled=false;btn.textContent='✨ Make creative TikTok';}
  };
})();
</script>
'''
    return html.replace('</body></html>', js + '</body></html>')


def register_ai_routes(app):
    @app.post('/api/ai-editor/render')
    async def ai_editor_render(
        files: list[UploadFile] = File(...),
        style: str = Form('viral'),
        target_length: int = Form(30),
        hook: str = Form(''),
    ):
        files = files[:8]
        if not files:
            raise HTTPException(400, 'Select at least one video file')
        if style not in {'viral', 'meme', 'clean', 'cinematic'}:
            style = 'viral'
        target_length = max(8, min(int(target_length or 30), 58))

        allowed = {'.mp4', '.mov', '.m4v', '.webm', '.mkv'}
        job = secrets.token_hex(8)
        uploaded = []
        total_bytes = 0
        max_total = 300 * 1024 * 1024

        try:
            for i, up in enumerate(files):
                ext = Path(up.filename or '').suffix.lower()
                if ext not in allowed:
                    raise HTTPException(400, f'{up.filename or "File"} is not a supported video type')
                p = AI_OUT / f'{job}-upload-{i}{ext}'
                with p.open('wb') as out:
                    while True:
                        chunk = await up.read(1024 * 1024)
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                        if total_bytes > max_total:
                            raise HTTPException(413, 'Uploads are limited to 300 MB total')
                        out.write(chunk)
                uploaded.append(p)

            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            per_clip = max(2.2, min(8.0, target_length / max(1, len(uploaded))))
            if style == 'meme':
                per_clip = min(per_clip, 3.8)
            elif style == 'viral':
                per_clip = min(per_clip, 4.6)
            elif style == 'clean':
                per_clip = min(7.0, per_clip + 1.0)

            segs = []
            total = 0.0
            hook_text = _escape_drawtext(hook or ('WAIT FOR IT...' if style == 'meme' else ''))

            for i, src in enumerate(uploaded):
                remaining = target_length - total
                if remaining < 0.5:
                    break
                dur = min(per_clip, remaining)
                seg = AI_OUT / f'{job}-seg-{i}.mp4'

                # Vertical 9:16 composition: blurred full-height background + crisp centered foreground.
                fg_width = 1040 if style in {'viral', 'meme'} else 1000
                sat = {'viral': '1.18', 'meme': '1.28', 'clean': '1.04', 'cinematic': '0.95'}[style]
                contrast = {'viral': '1.08', 'meme': '1.12', 'clean': '1.02', 'cinematic': '1.10'}[style]
                base = (
                    f"[0:v]split=2[bg][fg];"
                    f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:8[bg2];"
                    f"[fg]scale={fg_width}:-2,eq=saturation={sat}:contrast={contrast}[fg2];"
                    f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2"
                )
                if style in {'viral', 'meme'}:
                    base += ",unsharp=5:5:0.55:3:3:0.0"
                if i == 0 and hook_text:
                    base += (
                        ",drawbox=x=45:y=100:w=990:h=230:color=black@0.62:t=fill"
                        f",drawtext=text='{hook_text}':fontsize=62:fontcolor=white:x=(w-text_w)/2:y=155:borderw=4:bordercolor=black"
                    )
                # Tiny fades make the automated cuts feel intentional while staying punchy.
                fade_out = max(0.1, dur - 0.12)
                base += f",fade=t=in:st=0:d=0.08,fade=t=out:st={fade_out:.3f}:d=0.12[v]"

                cmd = [
                    ffmpeg, '-y', '-i', str(src), '-t', f'{dur:.3f}',
                    '-filter_complex', base,
                    '-map', '[v]', '-map', '0:a?',
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-ar', '44100', '-ac', '2',
                    '-movflags', '+faststart', str(seg)
                ]
                cp = subprocess.run(cmd, capture_output=True, text=True)
                if cp.returncode:
                    # Some uploads have no decodable audio or odd timestamps; retry video-only.
                    cmd2 = [
                        ffmpeg, '-y', '-i', str(src), '-t', f'{dur:.3f}',
                        '-filter_complex', base, '-map', '[v]',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p',
                        '-an', '-movflags', '+faststart', str(seg)
                    ]
                    cp = subprocess.run(cmd2, capture_output=True, text=True)
                if cp.returncode:
                    raise HTTPException(500, f'Could not edit {files[i].filename}: ' + cp.stderr[-220:])
                segs.append(seg)
                total += dur

            if not segs:
                raise HTTPException(400, 'No usable video clips were found')

            concat = AI_OUT / f'{job}.txt'
            concat.write_text(''.join(f"file '{p.as_posix()}'\n" for p in segs), encoding='utf-8')
            dest = Path('/tmp/clipforge') / f'ai-{job}.mp4'
            dest.parent.mkdir(parents=True, exist_ok=True)
            cp = subprocess.run([
                ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', str(concat),
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-c:a', 'aac',
                '-movflags', '+faststart', str(dest)
            ], capture_output=True, text=True)
            if cp.returncode:
                raise HTTPException(500, 'Final AI edit failed: ' + cp.stderr[-240:])

            return {
                'media_url': '/media/' + dest.name,
                'download_url': '/download/' + dest.name,
                'duration': min(total, 58.0),
                'clips_used': len(segs),
                'style': style,
            }
        finally:
            for p in uploaded:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
