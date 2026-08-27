import studio_app
from preview_patch import apply_preview_patch

studio_app.HTML = apply_preview_patch(studio_app.HTML)
app = studio_app.app
