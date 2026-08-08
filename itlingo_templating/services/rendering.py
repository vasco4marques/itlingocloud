"""Jinja2 helpers shared by the DOCX and XLSX renderers.

Rendering is lenient: missing fields resolve to blank instead of failing, so
partial specifications still produce a document.
"""

import json
import os
import re


OFFICE_TEMPLATE_FORMATS = frozenset({"docx", "xlsx"})


def template_format(filename, content):
    """Return an Office format or any extension whose content is UTF-8 text."""
    extension = os.path.splitext(filename or "")[1].lower().lstrip(".")
    if not extension:
        return None
    if extension in OFFICE_TEMPLATE_FORMATS:
        return extension
    try:
        content.decode("utf-8")
    except (AttributeError, UnicodeDecodeError):
        return None
    return extension if b"\x00" not in content else None


def lenient_env():
    """Jinja2 environment used by every renderer.

    ChainableUndefined keeps *missing* keys blank; finalize keeps present-but
    -None values (e.g. an unset version/vendor) blank instead of printing "None".
    """
    import jinja2

    env = jinja2.Environment(
        undefined=jinja2.ChainableUndefined,
        finalize=lambda v: "" if v is None else v,
        keep_trailing_newline=True,
    )
    default_dumps = env.policies["json.dumps_function"] or json.dumps

    def dumps_json_safe(value, **kwargs):
        def undefined_as_null(item):
            if isinstance(item, jinja2.Undefined):
                return None
            raise TypeError(
                "Object of type %s is not JSON serializable"
                % type(item).__name__
            )

        kwargs.setdefault("default", undefined_as_null)
        return default_dumps(value, **kwargs)

    env.policies["json.dumps_function"] = dumps_json_safe
    return env


def render_filename(pattern, context, fallback, extension):
    """Render a safe output filename and force the template's extension."""
    name = ""
    if pattern:
        try:
            name = lenient_env().from_string(pattern).render(context).strip()
        except Exception:
            name = ""
    name = name or fallback
    if not name.lower().endswith(extension):
        stem, current_extension = os.path.splitext(name)
        name = "%s%s" % (stem if current_extension else name, extension)
    return re.sub(r"[\\/:*?\"<>|]+", "_", name)
