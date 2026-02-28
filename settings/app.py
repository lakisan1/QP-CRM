import os
import sys
from flask import Flask, render_template, request, make_response, redirect

# Ensure shared modules can be imported
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from shared.config import STATIC_DIR
from shared.utils import _, get_current_language

app = Flask(
    __name__,
    static_folder=STATIC_DIR,
    static_url_path="/static",
    template_folder="templates"
)

@app.context_processor
def inject_helpers():
    theme = request.cookies.get('theme', 'dark')
    lang = get_current_language()
    return dict(theme=theme, _=lambda text: _(text, lang), current_lang=lang)

@app.route("/", methods=["GET", "POST"])
def settings_index():
    if request.method == "POST":
        theme = request.form.get("theme", "dark")
        date_format = request.form.get("date_format", "YYYY-MM-DD")
        
        # Redirect back to the central landing page (/)
        resp = make_response(redirect("/"))
        
        # Set cookies for 1 year
        max_age_seconds = 60 * 60 * 24 * 365
        resp.set_cookie('theme', theme, max_age=max_age_seconds, path='/')
        resp.set_cookie('date_format', date_format, max_age=max_age_seconds, path='/')
        
        return resp
        
    current_theme = request.cookies.get('theme', 'dark')
    current_date_format = request.cookies.get('date_format', 'YYYY-MM-DD')
    
    return render_template("settings.html", current_theme=current_theme, current_date_format=current_date_format)

if __name__ == "__main__":
    app.run(port=5006, debug=True)
