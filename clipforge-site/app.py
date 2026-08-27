import studio_app
from preview_patch import apply_preview_patch
from ai_editor_patch import apply_ai_editor_patch, register_ai_routes
from ai_render_fix import register_ai_render_fix

studio_app.HTML = apply_ai_editor_patch(apply_preview_patch(studio_app.HTML))
register_ai_routes(studio_app.app)
register_ai_render_fix(studio_app.app)
app = studio_app.app
