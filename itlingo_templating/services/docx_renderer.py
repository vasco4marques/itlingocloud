"""Render a DOCX template against the canonical model using docxtpl (Jinja2).

Rendering is lenient: missing fields resolve to blank instead of failing, so
partial specifications still produce a document.
"""

import io
import re

from .rendering import lenient_env, render_filename  # noqa: F401 (re-exported)


def render_docx(template_bytes, context):
    """Render the DOCX *template_bytes* with *context*; return DOCX bytes."""
    from docxtpl import DocxTemplate

    tpl = DocxTemplate(io.BytesIO(template_bytes))
    document = tpl.get_docx()
    try:
        tpl.render(context, jinja_env=lenient_env())
    except (ImportError, UnicodeDecodeError):
        raise
    except Exception as error:
        import jinja2

        syntax = isinstance(error, (jinja2.TemplateSyntaxError, jinja2.TemplateAssertionError))
        prefix = (
            "DOCX template error: "
            if syntax
            else "DOCX template could not be rendered with this specification: "
        )
        hint = _template_hint(document, error)
        raise ValueError("%s%s: %s" % (prefix, hint, str(error))) from error
    out = io.BytesIO()
    tpl.save(out)
    return out.getvalue()


def _template_hint(document, error):
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(paragraph.text for paragraph in cell.paragraphs)
    template_paragraphs = [
        text for text in paragraphs if "{{" in text or "{%" in text
    ]
    message = str(error)
    quoted_tokens = re.findall(r"'([^']+)'", message)
    for token in quoted_tokens:
        for text in template_paragraphs:
            if re.search(r"\b%s\b" % re.escape(token), text):
                return 'template text "%s"' % text
    ignored_tokens = {
        "encountered", "unknown", "tag", "object", "has", "no", "attribute",
        "template", "error", "expected", "end", "of", "block", "is", "not",
        "defined", "type", "argument", "filter", "test",
    }
    identifier_tokens = [
        token for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", message)
        if token.lower() not in ignored_tokens
    ]
    for token in identifier_tokens:
        for text in template_paragraphs:
            if re.search(r"\b%s\b" % re.escape(token), text):
                return 'template text "%s"' % text
    if template_paragraphs:
        return 'template text "%s"' % template_paragraphs[0]
    return "document template"
