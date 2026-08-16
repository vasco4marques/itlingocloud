"""Render UTF-8 text templates with the shared Jinja2 environment."""

from .rendering import render_best_effort


def render_text(template_bytes, context):
    """Render UTF-8 text bytes, marking template failures in the output.

    Text template formats are deliberately decoded strictly. This avoids treating
    an accidentally uploaded binary file as text and returning corrupted output.
    """
    template = template_bytes.decode("utf-8")
    rendered, _findings = render_best_effort(template, context)
    return rendered.encode("utf-8")
