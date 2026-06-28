"""Pure Markdown -> Telegram rich-message HTML converter.

Parses a Google-Docs Markdown export with ``markdown-it-py`` and renders the
rich-message HTML vocabulary ``sendRichMessage`` accepts. Its only side effect is
calling the injected :class:`~src.post.media.MediaStore` to host inline base64
images; everything else is a pure string transform.

Security contract (tech-spec Decision 1): every text node AND attribute value is
HTML-escaped, and ``href``/``src`` URL schemes are allow-listed
(``https``/``http``/``mailto``/``tel``/``tg``/``#anchor``) so the renderer can
never emit an injectable string. ``data:`` is rejected for links; for images it is
intercepted, decoded, and hosted via the media store.
"""

from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.rules_inline import StateInline
from markdown_it.token import Token
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin

from src.post.media import MediaStore

# Allow-listed link schemes for href (tech-spec Decision 1). data:/javascript: etc.
# are rejected. Anchors (#...) and scheme-relative refs handled separately.
_ALLOWED_LINK_SCHEMES = ("https:", "http:", "mailto:", "tel:", "tg:")

# Pulls the base64 payload out of a `data:<mime>;base64,<payload>` URI.
_DATA_URI_RE = re.compile(r"^data:[^,]*;base64,(?P<payload>.*)$", re.IGNORECASE | re.DOTALL)
_DETAILS_RE = re.compile(r"^(?P<kind>details|details-open)(?:\s+(?P<summary>.*))?$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_MEDIA_ATTACHMENTS = 50


class _MediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


_MEDIA_EXTENSIONS: dict[str, _MediaKind] = {
    ".jpg": _MediaKind.IMAGE,
    ".jpeg": _MediaKind.IMAGE,
    ".png": _MediaKind.IMAGE,
    ".webp": _MediaKind.IMAGE,
    ".heic": _MediaKind.IMAGE,
    ".heif": _MediaKind.IMAGE,
    ".gif": _MediaKind.VIDEO,
    ".mp4": _MediaKind.VIDEO,
    ".mov": _MediaKind.VIDEO,
    ".m4v": _MediaKind.VIDEO,
    ".webm": _MediaKind.VIDEO,
    ".mp3": _MediaKind.AUDIO,
    ".ogg": _MediaKind.AUDIO,
    ".oga": _MediaKind.AUDIO,
    ".m4a": _MediaKind.AUDIO,
    ".aac": _MediaKind.AUDIO,
    ".wav": _MediaKind.AUDIO,
    ".flac": _MediaKind.AUDIO,
}


def _href_allowed(href: str) -> bool:
    h = href.strip()
    if h.startswith("#"):
        return True
    lowered = h.lower()
    return any(lowered.startswith(scheme) for scheme in _ALLOWED_LINK_SCHEMES)


def _parse_link_allowed(href: str) -> bool:
    # Let markdown-it tokenize every link/image so the renderer can consistently
    # apply the allow-list. If parse-time validation rejects a URL, markdown-it
    # leaves the original `[text](url)` source visible as text; render-time
    # rejection preserves only the link text and never emits an unsafe attribute.
    return True


def _img_src_allowed(src: str) -> bool:
    lowered = src.strip().lower()
    return lowered.startswith("https:") or lowered.startswith("http:")


def _classify_external_media(src: str) -> _MediaKind | None:
    value = src.strip()
    decoded_value = unquote(value)
    if _CONTROL_CHARS_RE.search(value) or "\\" in value or "\\" in decoded_value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.netloc or parsed.username is not None or parsed.password is not None:
        return None
    decoded_netloc = unquote(parsed.netloc)
    if any(char in decoded_netloc for char in ("@", "/", "\\", "?", "#")):
        return None

    path = unquote(parsed.path)
    if _CONTROL_CHARS_RE.search(path) or "\\" in path:
        return None
    lowered_path = path.lower()
    for extension, kind in _MEDIA_EXTENSIONS.items():
        if lowered_path.endswith(extension):
            return kind
    return None


def _is_escaped(src: str, pos: int) -> bool:
    backslashes = 0
    cursor = pos - 1
    while cursor >= 0 and src[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _spoiler_plugin(md: MarkdownIt) -> None:
    md.inline.add_terminator_char("|")

    def tokenize_spoiler(state: StateInline, silent: bool) -> bool:
        start = state.pos
        maximum = state.posMax
        if start + 4 > maximum or state.src[start : start + 2] != "||":
            return False
        if silent:
            return False

        end = start + 2
        while True:
            end = state.src.find("||", end)
            if end < 0:
                return False
            if not _is_escaped(state.src, end):
                break
            end += 2

        if end == start + 2:
            return False

        children: list[Token] = []
        state.md.inline.parse(state.src[start + 2 : end], state.md, state.env, children)

        token = state.push("spoiler", "", 0)
        token.markup = "||"
        token.children = children
        state.pos = end + 2
        return True

    md.inline.ruler.before("text", "spoiler", tokenize_spoiler)


class _MediaState:
    """Tracks 0-based media order and collects indices that failed to render."""

    def __init__(self) -> None:
        self.index = 0
        self.failed: list[int] = []
        self.media_count = 0


def markdown_to_rich_html(md: str, media_store: MediaStore) -> tuple[str, list[int]]:
    """Convert Markdown to the rich-message HTML string Telegram accepts.

    Returns the HTML plus the **0-based** indices of images that could not be
    hosted (decode error, non-raster/rejected content, oversize, or a disallowed
    scheme). The 1-based "№1, №3" display offset is the handler's job, not this
    converter's.
    """
    # html=False escapes raw HTML blocks and inline HTML so the renderer can only
    # emit the tags it constructs itself — satisfying the tech-spec Decision 1
    # escaping contract. Google-Docs Markdown exports contain no raw HTML, so this
    # is not a functional regression.
    parser = (
        MarkdownIt(options_update={"html": False})
        .use(_spoiler_plugin)
        .use(dollarmath_plugin, allow_digits=False)
        .use(
            container_plugin,
            "details",
            validate=lambda params, markup: _DETAILS_RE.match(params.strip()) is not None,
        )
        .use(footnote_plugin)
        .enable(["table", "strikethrough"])
    )
    # Parse all link/image destinations first; render rules below apply the URL
    # allow-lists and decide whether to emit an attribute, host an image, or keep
    # only visible text.
    parser.validateLink = _parse_link_allowed

    state = _MediaState()
    rules = parser.renderer.rules

    def render_token_with_tag(tag: str):
        def _open(tokens, idx, options, env):
            return f"<{tag}>"

        def _close(tokens, idx, options, env):
            return f"</{tag}>"

        return _open, _close

    b_open, b_close = render_token_with_tag("b")
    rules["strong_open"] = b_open
    rules["strong_close"] = b_close

    i_open, i_close = render_token_with_tag("i")
    rules["em_open"] = i_open
    rules["em_close"] = i_close

    def render_spoiler(tokens, idx, options, env):
        children = tokens[idx].children or []
        content = parser.renderer.renderInline(children, options, env)
        return f"<tg-spoiler>{content}</tg-spoiler>"

    rules["spoiler"] = render_spoiler
    rules["text_special"] = lambda tokens, idx, options, env: escapeHtml(tokens[idx].content)

    def render_math_inline(tokens, idx, options, env):
        return f"<tg-math>{escapeHtml(tokens[idx].content)}</tg-math>"

    def render_math_block(tokens, idx, options, env):
        content = escapeHtml(tokens[idx].content.strip("\n"))
        if footnote_paragraph_seen:
            return _footnote_text_separator() + content
        return f"<tg-math-block>{content}</tg-math-block>\n"

    rules["math_inline"] = render_math_inline
    rules["math_block"] = render_math_block
    rules["math_block_label"] = render_math_block

    def render_details(self, tokens, idx, options, env):
        token = tokens[idx]
        if token.nesting != 1:
            if footnote_paragraph_seen:
                return ""
            return "</details>\n"

        match = _DETAILS_RE.match(token.info.strip())
        if match is None:
            return ""
        summary = match.group("summary") or "Подробнее"
        rendered_summary = parser.renderInline(summary, {})
        if footnote_paragraph_seen:
            return _footnote_text_separator() + rendered_summary
        open_attr = " open" if match.group("kind") == "details-open" else ""
        return f"<details{open_attr}><summary>{rendered_summary}</summary>\n"

    parser.add_render_rule("container_details_open", render_details)
    parser.add_render_rule("container_details_close", render_details)

    # Per-link rejection flag: when link_open drops a disallowed href, the
    # matching link_close must drop its </a> too (keeping the link text).
    rejected_links: list[bool] = []

    def render_link_open(tokens, idx, options, env):
        href = tokens[idx].attrGet("href") or ""
        if not _href_allowed(href):
            rejected_links.append(True)
            return ""
        rejected_links.append(False)
        return f'<a href="{escapeHtml(href)}">'

    def render_link_close(tokens, idx, options, env):
        rejected = rejected_links.pop() if rejected_links else False
        return "" if rejected else "</a>"

    rules["link_open"] = render_link_open
    rules["link_close"] = render_link_close

    def _footnote_name(tokens, idx) -> str:
        # Telegram references are local anchors. Use the parser's numeric id
        # instead of the raw Markdown label so the generated attribute is safe.
        footnote_id = int(tokens[idx].meta.get("id", 0)) + 1
        return f"footnote-{footnote_id}"

    def render_footnote_ref(tokens, idx, options, env):
        name = _footnote_name(tokens, idx)
        footnote_id = int(tokens[idx].meta.get("id", 0)) + 1
        sub_id = int(tokens[idx].meta.get("subId", 0)) + 1
        ref_name = (
            f"footnote-ref-{footnote_id}" if sub_id == 1 else f"footnote-ref-{footnote_id}-{sub_id}"
        )
        return f'<a name="{ref_name}"></a><sup><a href="#{name}">{footnote_id}</a></sup>'

    rules["footnote_ref"] = render_footnote_ref
    rules["footnote_block_open"] = lambda tokens, idx, options, env: ""
    rules["footnote_block_close"] = lambda tokens, idx, options, env: ""
    rules["footnote_anchor"] = lambda tokens, idx, options, env: ""

    footnote_paragraph_seen: list[bool] = []
    footnote_id_stack: list[int] = []

    def _footnote_text_separator() -> str:
        if not footnote_paragraph_seen:
            return ""
        if footnote_paragraph_seen[-1]:
            return " "
        footnote_paragraph_seen[-1] = True
        return ""

    def render_footnote_open(tokens, idx, options, env):
        footnote_id = int(tokens[idx].meta.get("id", 0)) + 1
        footnote_id_stack.append(footnote_id)
        footnote_paragraph_seen.append(False)
        return f'<a name="{_footnote_name(tokens, idx)}"></a><footer>{footnote_id}. '

    def render_footnote_close(tokens, idx, options, env):
        footnote_id = footnote_id_stack.pop() if footnote_id_stack else 1
        if footnote_paragraph_seen:
            footnote_paragraph_seen.pop()
        return f' <a href="#footnote-ref-{footnote_id}">↩</a></footer>'

    rules["footnote_open"] = render_footnote_open
    rules["footnote_close"] = render_footnote_close

    media_block_context: list[bool] = []
    suppress_paragraph_context: list[bool] = []

    def _render_media(kind: _MediaKind, src: str, caption: str) -> str:
        if kind is _MediaKind.IMAGE:
            media = f'<img src="{escapeHtml(src)}" />'
        elif kind is _MediaKind.VIDEO:
            media = f'<video src="{escapeHtml(src)}"></video>'
        else:
            media = f'<audio src="{escapeHtml(src)}"></audio>'

        if not caption:
            return media
        return f"<figure>{media}<figcaption>{escapeHtml(caption)}</figcaption></figure>"

    def render_image(tokens, idx, options, env):
        token: Token = tokens[idx]
        current = state.index
        state.index += 1
        src = token.attrGet("src") or ""
        caption = token.attrGet("title") or ""

        if footnote_paragraph_seen:
            return escapeHtml(token.content)
        if not media_block_context or not media_block_context[-1]:
            return escapeHtml(token.content)

        if state.media_count >= _MAX_MEDIA_ATTACHMENTS:
            state.failed.append(current)
            return ""

        data_match = _DATA_URI_RE.match(src.strip())
        if data_match:
            hosted = media_store.save(data_match.group("payload"))
            if hosted is None:
                state.failed.append(current)
                return ""
            resolved = hosted
            kind = _MediaKind.IMAGE
        elif _img_src_allowed(src):
            kind = _classify_external_media(src)
            if kind is None:
                state.failed.append(current)
                return ""
            resolved = src
        else:
            # Disallowed scheme (e.g. javascript:) — drop and mark failed.
            state.failed.append(current)
            return ""

        state.media_count += 1
        return _render_media(kind, resolved, caption)

    rules["image"] = render_image

    def _empty_inside_footnote(token_type: str) -> None:
        base_rule = parser.renderer.rules.get(token_type)

        def _render(tokens, idx, options, env):
            if footnote_paragraph_seen:
                return ""
            if base_rule is not None:
                return base_rule(tokens, idx, options, env)
            return parser.renderer.renderToken(tokens, idx, options, env)

        rules[token_type] = _render

    def _separator_inside_footnote(token_type: str) -> None:
        base_rule = parser.renderer.rules.get(token_type)

        def _render(tokens, idx, options, env):
            if footnote_paragraph_seen:
                return _footnote_text_separator()
            if base_rule is not None:
                return base_rule(tokens, idx, options, env)
            return parser.renderer.renderToken(tokens, idx, options, env)

        rules[token_type] = _render

    for block_token in (
        "bullet_list_open",
        "bullet_list_close",
        "ordered_list_open",
        "ordered_list_close",
        "list_item_open",
        "list_item_close",
        "blockquote_open",
        "blockquote_close",
        "table_open",
        "table_close",
        "thead_open",
        "thead_close",
        "tbody_open",
        "tbody_close",
        "tr_open",
        "tr_close",
        "th_close",
        "td_close",
        "heading_close",
        "hr",
    ):
        _empty_inside_footnote(block_token)

    for cell_token in ("heading_open", "th_open", "td_open"):
        _separator_inside_footnote(cell_token)

    base_code_block_rule = parser.renderer.rules.get("code_block")
    base_fence_rule = parser.renderer.rules.get("fence")

    def _render_code_block(tokens, idx, options, env):
        if footnote_paragraph_seen:
            return _footnote_text_separator() + escapeHtml(tokens[idx].content.strip())
        if base_code_block_rule is not None:
            return base_code_block_rule(tokens, idx, options, env)
        return parser.renderer.renderToken(tokens, idx, options, env)

    def _render_fence(tokens, idx, options, env):
        if footnote_paragraph_seen:
            return _footnote_text_separator() + escapeHtml(tokens[idx].content.strip())
        if base_fence_rule is not None:
            return base_fence_rule(tokens, idx, options, env)
        return parser.renderer.renderToken(tokens, idx, options, env)

    rules["code_block"] = _render_code_block
    rules["fence"] = _render_fence

    # Telegram's rich-message renderer is a structured block model: whitespace and
    # newlines between block tags are collapsed by design, so adjacent block tags
    # render glued together with no vertical gap. There is no blank-line markup, and
    # the client already inserts its own gap before headings, around tables, lists
    # and images. To restore *only* the separation the client does NOT provide, emit
    # one visually-empty spacer `<p>&nbsp;</p>` before top-level TEXT paragraphs
    # after another text paragraph, heading, or divider; before top-level dividers
    # after text paragraphs/headings; and before top-level headings after dividers.
    # Media-only paragraphs, tables, lists, code blocks and rich details blocks keep
    # Telegram's native spacing so they do not gain stray blank lines.
    def _is_media_only_paragraph(tokens, open_idx) -> bool:
        # A `paragraph_open` whose `inline` body is just an image (plus whitespace/
        # softbreaks) — not a real text paragraph.
        inline = tokens[open_idx + 1] if open_idx + 1 < len(tokens) else None
        if inline is None or inline.type != "inline" or not inline.children:
            return False
        has_image = False
        for child in inline.children:
            if child.type == "image":
                has_image = True
            elif child.type in ("softbreak", "hardbreak"):
                continue
            elif child.type == "text" and not child.content.strip():
                continue
            else:
                return False
        return has_image

    def _media_only_paragraph_has_caption(tokens, open_idx) -> bool:
        inline = tokens[open_idx + 1] if open_idx + 1 < len(tokens) else None
        if inline is None or inline.type != "inline" or not inline.children:
            return False
        for child in inline.children:
            if child.type == "image" and child.attrGet("title"):
                return True
        return False

    def _previous_top_level(tokens, idx) -> tuple[Token | None, int | None]:
        for j in range(idx - 1, -1, -1):
            if tokens[j].hidden or tokens[j].level != 0:
                continue
            return tokens[j], j
        return None, None

    def _is_text_paragraph_close(tokens, idx) -> bool:
        return (
            idx is not None
            and idx >= 2
            and tokens[idx].type == "paragraph_close"
            and not _is_media_only_paragraph(tokens, idx - 2)
        )

    base_paragraph_open = parser.renderer.rules.get("paragraph_open")
    base_paragraph_close = parser.renderer.rules.get("paragraph_close")
    base_heading_open = parser.renderer.rules.get("heading_open")
    base_hr = parser.renderer.rules.get("hr")

    def render_paragraph_open(tokens, idx, options, env):
        if footnote_paragraph_seen:
            return _footnote_text_separator()

        out = ""
        token = tokens[idx]
        is_media_paragraph = _is_media_only_paragraph(tokens, idx)
        suppress_paragraph = is_media_paragraph and _media_only_paragraph_has_caption(tokens, idx)
        media_block_context.append(is_media_paragraph)
        suppress_paragraph_context.append(suppress_paragraph)
        if token.level == 0 and not is_media_paragraph:
            # Find the nearest preceding top-level block boundary.
            prev, prev_idx = _previous_top_level(tokens, idx)
            preceded_by_heading = prev is not None and prev.type == "heading_close"
            preceded_by_text_paragraph = _is_text_paragraph_close(tokens, prev_idx)
            preceded_by_hr = prev is not None and prev.type == "hr"
            if preceded_by_heading or preceded_by_text_paragraph or preceded_by_hr:
                # `&nbsp;` is an allowed Rich Message entity; emit it literally so
                # escapeHtml never turns `&` into `&amp;`.
                out += "<p>&nbsp;</p>"
        if suppress_paragraph:
            return out
        if base_paragraph_open is not None:
            return out + base_paragraph_open(tokens, idx, options, env)
        return out + parser.renderer.renderToken(tokens, idx, options, env)

    rules["paragraph_open"] = render_paragraph_open

    def render_paragraph_close(tokens, idx, options, env):
        if footnote_paragraph_seen:
            return ""
        suppress_paragraph = (
            suppress_paragraph_context.pop() if suppress_paragraph_context else False
        )
        if media_block_context:
            media_block_context.pop()
        if suppress_paragraph:
            return ""
        if base_paragraph_close is not None:
            return base_paragraph_close(tokens, idx, options, env)
        return parser.renderer.renderToken(tokens, idx, options, env)

    rules["paragraph_close"] = render_paragraph_close

    def render_heading_open(tokens, idx, options, env):
        if footnote_paragraph_seen:
            if base_heading_open is not None:
                return base_heading_open(tokens, idx, options, env)
            return parser.renderer.renderToken(tokens, idx, options, env)

        out = ""
        if tokens[idx].level == 0:
            prev, _prev_idx = _previous_top_level(tokens, idx)
            if prev is not None and prev.type == "hr":
                out += "<p>&nbsp;</p>"
        if base_heading_open is not None:
            return out + base_heading_open(tokens, idx, options, env)
        return out + parser.renderer.renderToken(tokens, idx, options, env)

    rules["heading_open"] = render_heading_open

    def render_hr(tokens, idx, options, env):
        if footnote_paragraph_seen:
            return ""

        out = ""
        if tokens[idx].level == 0:
            prev, prev_idx = _previous_top_level(tokens, idx)
            preceded_by_heading = prev is not None and prev.type == "heading_close"
            preceded_by_text_paragraph = _is_text_paragraph_close(tokens, prev_idx)
            if preceded_by_heading or preceded_by_text_paragraph:
                out += "<p>&nbsp;</p>"
        if base_hr is not None:
            return out + base_hr(tokens, idx, options, env)
        return out + parser.renderer.renderToken(tokens, idx, options, env)

    rules["hr"] = render_hr

    html = parser.render(md)
    return html, state.failed
