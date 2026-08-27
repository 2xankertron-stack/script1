import studio_app
from remove_short_editor_patch import remove_short_editor

studio_app.HTML = remove_short_editor(studio_app.HTML)
app = studio_app.app
