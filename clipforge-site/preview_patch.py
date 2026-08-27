def apply_preview_patch(html: str) -> str:
    """Add an official Twitch embed to the phone preview without downloading clip media."""
    html = html.replace(
        '<div class="previewHint">Preview is for layout. After rendering, the actual MP4 plays inside the phone.</div>',
        '<div class="previewHint">Public Twitch clips play here using the Twitch embed — no clip download is needed. Trim markers and overlay text remain a layout preview until export.</div>'
    )
    html = html.replace(
        '>Render selected clips</button>',
        '>Export MP4 (requires permission)</button>'
    )

    patch = r'''
<script>
(function(){
  function ensureTwitchFrame(){
    let frame=document.getElementById('phoneTwitchEmbed');
    if(frame)return frame;
    const screen=document.getElementById('phoneScreen');
    if(!screen)return null;
    frame=document.createElement('iframe');
    frame.id='phoneTwitchEmbed';
    frame.className='phoneMedia hidden';
    frame.title='Twitch clip preview';
    frame.allow='autoplay; fullscreen';
    frame.setAttribute('allowfullscreen','');
    frame.setAttribute('frameborder','0');
    frame.style.border='0';
    frame.style.zIndex='2';
    frame.style.position='absolute';
    frame.style.inset='0';
    frame.style.width='100%';
    frame.style.height='100%';
    const thumb=document.getElementById('phoneThumb');
    if(thumb && thumb.parentNode===screen)screen.insertBefore(frame,thumb.nextSibling);else screen.prepend(frame);
    return frame;
  }

  const originalSync=window.syncPreview;
  window.syncPreview=function(){
    if(typeof originalSync==='function')originalSync();
    const frame=ensureTwitchFrame();
    if(!frame)return;
    const count=Array.isArray(window.selected)?window.selected.length:(typeof selected!=='undefined'?selected.length:0);
    const list=(typeof selected!=='undefined')?selected:window.selected;
    const ready=(typeof renderedReady!=='undefined')?renderedReady:false;
    if(!count || ready){
      frame.classList.add('hidden');
      if(ready)frame.src='about:blank';
      return;
    }
    const i=(typeof previewIndex!=='undefined')?Math.min(previewIndex,count-1):0;
    const c=list[i];
    if(!c || !c.id || String(c.id).startsWith('demo')){
      frame.classList.add('hidden');
      frame.src='about:blank';
      return;
    }
    const parent=location.hostname;
    const wanted='https://clips.twitch.tv/embed?clip='+encodeURIComponent(c.id)+'&parent='+encodeURIComponent(parent)+'&autoplay=false&muted=false';
    if(frame.dataset.clipId!==String(c.id)){
      frame.src=wanted;
      frame.dataset.clipId=String(c.id);
    }
    frame.classList.remove('hidden');
    const thumb=document.getElementById('phoneThumb');
    const demo=document.getElementById('demoCanvas');
    const video=document.getElementById('phoneVideo');
    if(thumb)thumb.classList.add('hidden');
    if(demo)demo.classList.add('hidden');
    if(video)video.classList.add('hidden');
    const status=document.getElementById('previewStatus');
    if(status)status.textContent='Twitch preview · no download';
  };

  const originalInvalidate=window.invalidateRender;
  window.invalidateRender=function(){
    if(typeof originalInvalidate==='function')originalInvalidate();
    const frame=ensureTwitchFrame();
    if(frame){frame.classList.add('hidden');frame.src='about:blank';frame.dataset.clipId='';}
  };

  // Make the editor's Preview buttons explicitly mean public playback, not export.
  const originalRenderEditor=window.renderEditor;
  window.renderEditor=function(doPreview=true){
    if(typeof originalRenderEditor==='function')originalRenderEditor(doPreview);
    document.querySelectorAll('.editorItem button').forEach(btn=>{
      if(btn.textContent.trim()==='Preview')btn.textContent='Play preview';
    });
  };

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',()=>{ensureTwitchFrame();window.renderEditor();window.syncPreview();});
  }else{
    ensureTwitchFrame();window.renderEditor();window.syncPreview();
  }
})();
</script>
'''
    return html.replace('</body></html>', patch + '</body></html>')
