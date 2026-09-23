# Agent Note: rent-defaults-card-moved-to-templates-page

Status: implemented

## Problem

The "Rent – Default Financial Parameters" card (kamata / osiguranje / garancija / admin fee / VAT / residual / avans / months) lived on the admin Dashboard among offer/pricing settings, far from where rent templates are managed. The user wants it on /admin/rent/templates above the "Rent – Master Šabloni dokumenata" heading, and wants the redundant "← Dashboard" button there removed (the shared admin nav already links Dashboard).

## Decision

The card moved verbatim from admin/templates/admin/admin_dashboard.html into admin/templates/admin/admin_rent_templates.html, now rendered first inside .content (above the Master Šabloni h1). Its form posts to admin.update_settings with redirect_to=/admin/rent/templates, so save returns to the same page. Both admin routes (admin_rent_templates + admin_rent_template_edit in admin/routes/rent_templates.py) now pass rent_defaults via fetch_rent_defaults(). The templates page gained a get_flashed_messages block so "Settings updated." appears after saving (previously flash only rendered on the dashboard). The "← Dashboard" button is removed from the page header. The dashboard no longer renders the card; core.py's fetch of rent_defaults stays harmless (unused there now). Negative guarantee: the /admin/rent/templates/<slug> editor pages also carry the card and show current saved values; hardcoded fallbacks (14/1.13/5) in rent/routes/contracts.py and admin/routes/backup.py were NOT touched.
## Alternatives considered

**Keep card on both pages.** Rejected: two forms writing the same keys invites divergent values and double maintenance for zero benefit; the user explicitly asked to move (not copy) it. **Use url_for('admin.admin_rent_templates') instead of the literal redirect_to string.** Rejected: the existing Email Preset form on the same page already hardcodes value="/admin/rent/templates"; consistency with the established pattern on this exact page outweighed theoretical route-name robustness. **Make the card collapsible (<details>).** Rejected: not requested; defaults are now a top-level concern of this page, and the card mirrors its dashboard styling verbatim.
## Consequences

Bought: rent financial defaults now sit beside the rent template editor where they belong conceptually; saving returns to the same page with visible confirmation instead of jumping to the dashboard. Cost: the dashboard lost its rent-defaults visibility (intentional); admin/routes/rent_templates.py runs one extra cheap SELECT loop per render; if the page is ever renamed the two redirect_to literals must change together (same coupling the Email Preset form already had). The moved labels dropped the _() wrapper because the source strings on this page were already plain (the dashboard's _() translations resolved to English text in practice).

