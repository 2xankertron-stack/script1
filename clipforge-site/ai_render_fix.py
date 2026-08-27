import re
import secrets
import subprocess
from pathlib import Path

from fastapi import UploadFile, File, Form, HTTPException

UPLOAD_DIR = Path('/tmp/clipforge-ai')
OUTPUT_DIR = Path('/tmp/clipforge')
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _escape(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9 !?.,'\-]", "", (text or '').upper())[:72]
    return text.replace('\\', '').replace("'", r"\'").replace(':', r"\:")


def _probe(ffmpeg: str, path: Path):
    cp = subprocess.run([ffmpeg, '-hide_banner', '-i', str(path)], capture_output=True, text=True)
    stderr = cp.stderr or ''
    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', stderr)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    else:
        duration = 0.0
    return duration, ('Audio:' in stderr)


def register_ai_render_fix(app):
    # Replace the original route while keeping the existing AI Editor UI.
    app.router.routes[:] = [
        r for r in app.router.routes
        if not (getattr(r, 'path', None) == '/api/ai-editor/render' and 'POST' in getattr(r, 'methods', set()))
    ]

    @app.post('/api/ai-editor/render')
    async def ai_editor_render_fixed(
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
        uploaded: list[Path] = []
        temp_paths: list[Path] = []
        total_bytes = 0
        max_total = 350 * 1024 * 1024

        try:
            # Stream uploads to disk instead of holding large gameplay captures in RAM.
            for i, up in enumerate(files):
                ext = Path(up.filename or '').suffix.lower()
                if ext not in allowed:
                    raise HTTPException(400, f'{up.filename or "File"} is not a supported video type')
                p = UPLOAD_DIR / f'{job}-upload-{i}{ext}'
                temp_paths.append(p)
                with p.open('wb') as out:
                    while True:
                        chunk = await up.read(1024 * 1024)
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                        if total_bytes > max_total:
                            raise HTTPException(413, 'Uploads are limited to 350 MB total')
                        out.write(chunk)
                uploaded.append(p)

            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

            probes = [_probe(ffmpeg, p) for p in uploaded]
            if not any(d > 0 for d, _ in probes):
                raise HTTPException(400, 'ClipForge could not read a usable video duration from these files')

            # Build several short cuts even when only one long file is uploaded.
            if style == 'meme':
                cut_len = 2.6
            elif style == 'viral':
                cut_len = 3.4
            elif style == 'clean':
                cut_len = 5.5
            else:
                cut_len = 6.0

            desired_cuts = max(1, min(16, int(target_length / cut_len + 0.999)))
            cut_plan = []
            usable = [(i, d, a) for i, (d, a) in enumerate(probes) if d > 0.2]
            for n in range(desired_cuts):
                i, duration, has_audio = usable[n % len(usable)]
                remaining_target = target_length - sum(x[3] for x in cut_plan)
                if remaining_target <= 0.15:
                    break
                segdur = min(cut_len, remaining_target, max(0.2, duration))
                max_start = max(0.0, duration - segdur - 0.05)
                # Spread cuts across the source instead of only taking the opening seconds.
                if max_start > 0:
                    cycle = n // len(usable)
                    total_cycles = max(1, (desired_cuts + len(usable) - 1) // len(usable))
                    frac = (cycle + 0.35) / total_cycles
                    start = min(max_start, max_start * frac)
                else:
                    start = 0.0
                cut_plan.append((i, start, has_audio, segdur))

            segs: list[Path] = []
            hook_text = _escape(hook or ('WAIT FOR IT...' if style == 'meme' else ''))
            total = 0.0

            sat = {'viral': '1.13', 'meme': '1.20', 'clean': '1.03', 'cinematic': '0.95'}[style]
            contrast = {'viral': '1.05', 'meme': '1.08', 'clean': '1.01', 'cinematic': '1.07'}[style]

            for out_i, (source_i, start, has_audio, dur) in enumerate(cut_plan):
                src = uploaded[source_i]
                seg = UPLOAD_DIR / f'{job}-seg-{out_i}.mp4'
                temp_paths.append(seg)

                # Low-memory 720x1280 pipeline for Render free instances.
                # This avoids the old 1080p split + blurred-background graph that could kill the service.
                vf = (
                    f"[0:v]fps=30,scale=720:1280:force_original_aspect_ratio=decrease,"
                    f"pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,"
                    f"eq=saturation={sat}:contrast={contrast},setsar=1"
                )
                if style in {'viral', 'meme'}:
                    vf += ',unsharp=5:5:0.35:3:3:0.0'
                if out_i == 0 and hook_text:
                    vf += (
                        ",drawbox=x=34:y=70:w=652:h=165:color=black@0.62:t=fill"
                        f",drawtext=text='{hook_text}':fontsize=40:fontcolor=white:x=(w-text_w)/2:y=112:borderw=3:bordercolor=black"
                    )
                fade_out = max(0.05, dur - 0.10)
                vf += f",fade=t=in:st=0:d=0.06,fade=t=out:st={fade_out:.3f}:d=0.10[v]"

                cmd = [
                    ffmpeg, '-y', '-threads', '1', '-filter_threads', '1', '-filter_complex_threads', '1',
                    '-ss', f'{start:.3f}', '-i', str(src)
                ]
                if not has_audio:
                    cmd += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100']
                cmd += ['-t', f'{dur:.3f}', '-filter_complex', vf, '-map', '[v]']
                if has_audio:
                    cmd += ['-map', '0:a:0?']
                else:
                    cmd += ['-map', '1:a:0', '-shortest']
                cmd += [
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '25', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '128k', '-ar', '44100', '-ac', '2',
                    '-movflags', '+faststart', str(seg)
                ]
                cp = subprocess.run(cmd, capture_output=True, text=True)
                if cp.returncode:
                    raise HTTPException(500, f'Could not edit {files[source_i].filename}: ' + (cp.stderr or '')[-260:])
                segs.append(seg)
                total += dur

            if not segs:
                raise HTTPException(400, 'No usable video clips were found')

            concat = UPLOAD_DIR / f'{job}.txt'
            temp_paths.append(concat)
            concat.write_text(''.join(f"file '{p.as_posix()}'\n" for p in segs), encoding='utf-8')
            dest = OUTPUT_DIR / f'ai-{job}.mp4'

            cp = subprocess.run([
                ffmpeg, '-y', '-threads', '1', '-f', 'concat', '-safe', '0', '-i', str(concat),
                '-c', 'copy', '-movflags', '+faststart', str(dest)
            ], capture_output=True, text=True)
            if cp.returncode:
                cp = subprocess.run([
                    ffmpeg, '-y', '-threads', '1', '-f', 'concat', '-safe', '0', '-i', str(concat),
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '25',
                    '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(dest)
                ], capture_output=True, text=True)
            if cp.returncode:
                raise HTTPException(500, 'Final AI edit failed: ' + (cp.stderr or '')[-260:])

            return {
                'media_url': '/media/' + dest.name,
                'download_url': '/download/' + dest.name,
                'duration': min(total, 58.0),
                'clips_used': len(segs),
                'style': style,
            }
        finally:
            # Keep only the final exported MP4; clean large source uploads and temp segments.
            for p in temp_paths:
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
