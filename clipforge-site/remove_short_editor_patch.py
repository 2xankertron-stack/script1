import re


def remove_short_editor(html: str) -> str:
    # Remove the Short Editor tab button.
    html = re.sub(
        r'<button id="editorTab" class="tab"[^>]*>Short Editor.*?</button>\s*',
        '',
        html,
        count=1,
        flags=re.S,
    )

    # Remove the full Short Editor panel.
    html = re.sub(
        r'<section id="editorPanel" class="tabPanel">.*?</section>\s*',
        '',
        html,
        count=1,
        flags=re.S,
    )

    # Remove the old selection-to-editor footer card.
    html = re.sub(
        r'<div class="card"><div class="row"><div><b id="selectionSummary">.*?</div></div></div>\s*',
        '',
        html,
        count=1,
        flags=re.S,
    )

    # Update the hero copy now that AI Editor is the main editing workflow.
    html = html.replace(
        'Scout clips, select several moments, then switch to the editor tab to arrange, trim, preview, render, and download your finished Short.',
        'Scout Twitch clips, then use AI Editor to turn your own selected video files into a creative vertical TikTok-style edit.'
    )

    # Hide any leftover clip-selection controls that only belonged to Short Editor.
    cleanup = r'''
<style>
#editorTab,#editorPanel,#selectionSummary{display:none!important}
</style>
<script>
(function(){
  function cleanShortEditorControls(){
    document.querySelectorAll('.clip button').forEach(function(btn){
      const t=(btn.textContent||'').trim();
      if(t==='Select clip' || t==='Selected ✓') btn.style.display='none';
    });
    document.querySelectorAll('button').forEach(function(btn){
      const t=(btn.textContent||'').trim();
      if(t==='Edit selected clips →') btn.closest('.card')?.remove();
    });
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',cleanShortEditorControls);
  else cleanShortEditorControls();
  new MutationObserver(cleanShortEditorControls).observe(document.documentElement,{childList:true,subtree:true});
})();
</script>
'''
    return html.replace('</body></html>', cleanup + '</body></html>')
