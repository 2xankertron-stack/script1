import studio_app
from ai_editor_patch import apply_ai_editor_patch, register_ai_routes
from ai_render_fix import register_ai_render_fix
from remove_short_editor_patch import remove_short_editor

studio_app.HTML = remove_short_editor(apply_ai_editor_patch(studio_app.HTML))
register_ai_routes(studio_app.app)
register_ai_render_fix(studio_app.app)
app = studio_app.app
