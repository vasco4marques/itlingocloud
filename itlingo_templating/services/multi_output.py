"""Multi-output text bundles: one UTF-8 template, many rendered text files.

A bundle template delimits each output with standalone Jinja comment fences::

    {# output: {{ spec_name }}_model.py #}
    class {{ root.name }}:
        pass
    {# endoutput #}

Templates without fences are legacy single-output templates and are left alone.
"""

import io
import re
import unicodedata
import zipfile
from .rendering import lenient_env, render_best_effort


class MultiOutputTemplateError(ValueError):
    """User-safe bundle syntax, filename, or rendering error."""


_OPEN = re.compile(r"^[ \t]*\{#[ \t]*output:[ \t]*(?P<name>.*?)[ \t]*#\}[ \t]*$")
_CLOSE = re.compile(r"^[ \t]*\{#[ \t]*endoutput[ \t]*#\}[ \t]*$")
_CANDIDATE = re.compile(r"^[ \t]*\{#[ \t]*(?:output|endoutput)\b.*$")
_UNSAFE = re.compile(r"[/\\:*?\"<>|]")


def _split_blocks(source):
    """Return ordered [(filename_template, body)] or None when marker-free."""
    blocks = []
    name = None
    body = []
    for number, raw_line in enumerate(source.splitlines(keepends=True), 1):
        line = raw_line.rstrip("\r\n")
        opening = _OPEN.match(line)
        if opening:
            if name is not None:
                raise MultiOutputTemplateError(
                    "Line %d: output block opened before the previous block "
                    "was closed with {# endoutput #}." % number
                )
            name = opening.group("name")
            body = []
            continue
        if _CLOSE.match(line):
            if name is None:
                raise MultiOutputTemplateError(
                    "Line %d: {# endoutput #} without a matching "
                    "{# output: ... #}." % number
                )
            blocks.append((name, "".join(body)))
            name = None
            continue
        if _CANDIDATE.match(line):
            raise MultiOutputTemplateError(
                "Line %d: malformed output fence." % number
            )
        if name is not None:
            body.append(raw_line)
        elif line.strip():
            raise MultiOutputTemplateError(
                "Line %d: content outside an output block is not allowed in a "
                "multi-output template." % number
            )
    if name is not None:
        raise MultiOutputTemplateError(
            "Unclosed output block; add {# endoutput #}."
        )
    return blocks


def _render(env, source, context, what, best_effort=False):
    if "\r\n" in source:
        env.newline_sequence = "\r\n"
    elif "\r" in source:
        env.newline_sequence = "\r"
    else:
        env.newline_sequence = "\n"
    try:
        if best_effort:
            rendered, _findings = render_best_effort(
                source, context, env=env
            )
            return rendered
        return env.from_string(source).render(**context)
    except Exception as error:
        raise MultiOutputTemplateError(
            "Could not render %s: %s" % (what, error)
        ) from error


def _validate_name(name, seen):
    if not name.strip() or name.strip() in (".", ".."):
        raise MultiOutputTemplateError(
            "Output filename %r is empty or invalid." % name
        )
    if name != name.strip():
        raise MultiOutputTemplateError(
            "Output filename %r must not begin or end with whitespace." % name
        )
    if (
        _UNSAFE.search(name)
        or any(unicodedata.category(char) == "Cc" for char in name)
    ):
        raise MultiOutputTemplateError(
            "Output filename %r must be a plain file name without path "
            "separators, control characters, or the characters : * ? \" < > |."
            % name
        )
    if name.endswith("."):
        raise MultiOutputTemplateError(
            "Output filename %r must not end with a dot." % name
        )
    if len(name.encode("utf-8")) > 255:
        raise MultiOutputTemplateError(
            "Output filename %r exceeds 255 bytes." % name
        )
    key = name.casefold()
    if key in seen:
        raise MultiOutputTemplateError(
            "Duplicate output filename %r; each output must have a distinct "
            "name." % name
        )
    seen.add(key)
    return name


_JINJA_EXPR = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")


def validate_output_template(template_bytes):
    """Return None for marker-free input, otherwise raw ordered header templates.

    Validates bundle structure and the literal part of each filename header;
    names containing Jinja expressions are only checked for their literal
    remainder, and their real safety/duplication is decided by
    ``render_outputs`` once a context exists.
    """
    source = template_bytes.decode("utf-8")
    if not any(_CANDIDATE.match(line) for line in source.splitlines()):
        return None
    names = [name for name, _body in _split_blocks(source)]
    seen = set()
    for index, name_template in enumerate(names, 1):
        dynamic = bool(_JINJA_EXPR.search(name_template))
        literal = _JINJA_EXPR.sub("", name_template).strip()
        if dynamic and not literal:
            continue
        try:
            _validate_name(literal, set() if dynamic else seen)
        except MultiOutputTemplateError as error:
            raise MultiOutputTemplateError(
                "Output %d filename: %s" % (index, error)
            ) from None
    return names


def render_outputs(template_bytes, context):
    """Return None for marker-free input, otherwise ordered [(name, bytes)]."""
    source = template_bytes.decode("utf-8")
    lines = [
        raw_line.rstrip("\r\n")
        for raw_line in source.splitlines(keepends=True)
    ]
    if not any(_CANDIDATE.match(line) for line in lines):
        return None

    blocks = _split_blocks(source)
    env = lenient_env()
    outputs = []
    seen = set()
    for index, (name_template, body) in enumerate(blocks, 1):
        name = _validate_name(
            _render(env, name_template, context, "output %d filename" % index),
            seen,
        )
        rendered = _render(env, body, context, "output %r" % name, True)
        outputs.append((name, rendered.encode("utf-8")))
    return outputs


def build_zip(outputs):
    """Return ZIP_DEFLATED archive bytes containing ordered entries."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in outputs:
            archive.writestr(name, data)
    return buffer.getvalue()
