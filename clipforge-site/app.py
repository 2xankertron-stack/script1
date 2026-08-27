import studio_app
from preview_patch import apply_preview_patch
from age_patch import apply_age_patch, register_age_routes

studio_app.HTML = apply_age_patch(apply_preview_patch(studio_app.HTML))
register_age_routes(studio_app.app)
app = studio_app.app
