"""Admin route groups (Phase 2 stage 5). Importing this package
registers every route group on admin.app's blueprint."""
from . import core, settings, presets, pdf_templates, backup, rounding, rent_templates  # noqa: F401
