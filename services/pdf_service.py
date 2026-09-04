"""PDF rendering services (Phase 2 stage 4).

The DB-stored PDF templates (pdf_templates.header_html/body_html/
footer_html) are Jinja sources entered by admins and, for custom
templates, arbitrary users -- Flask's render_template_string gave them the
full application Jinja environment, an SSTI hole (audit finding C4).
render_db_template_parts renders them in a jinja2 SandboxedEnvironment
instead:

* templates can only reach the explicitly provided context plus the
  globals pinned below (url_for, _, gettext, format_amount, format_date);
* app-level filters (format_date, md, int, safe, ...) are copied from the
  app's Jinja environment at call time so filter behavior stays identical;
* autoescape is on, matching Flask's behavior for string templates;
* direct access to request/session/g/config or template internals raises
  SecurityError now. The seeded System Default template uses only the
  pinned names, so its rendering is byte-identical to the previous
  render_template_string output.

The rent module does NOT use this service: rent document templates are
rendered by literal {{ placeholder }} string substitution in
rent/app.py, not Jinja, so there is no SSTI surface there.
"""

from jinja2.sandbox import SandboxedEnvironment

from shared.utils import format_amount, format_date

# Globals every DB template may use (audit C4 closure pins this allow-list).
SANDBOX_GLOBAL_NAMES = ("url_for", "_", "gettext", "format_amount", "format_date")


def render_db_template_parts(header_src, body_src, footer_src, ctx,
                             app_filters, url_for_func,
                             translate_func=None, gettext_func=None):
    """Render the three DB template parts in a sandboxed environment.

    Returns (header_html, body_html, footer_html). app_filters is the
    app's jinja_env.filters dict (passed by the caller at request time so
    this module does not need an app import).
    """
    env = SandboxedEnvironment(autoescape=True)
    env.filters.update(app_filters)
    env.globals.update(
        url_for=url_for_func,
        _=translate_func if translate_func is not None else (lambda x: x),
        gettext=gettext_func if gettext_func is not None else (lambda x: x),
        format_amount=format_amount,
        format_date=format_date,
    )
    render = env.from_string
    return (
        render(header_src).render(**ctx),
        render(body_src).render(**ctx),
        render(footer_src).render(**ctx),
    )
