import base64
import struct
import zlib

from src.post.markdown import markdown_to_rich_html
from src.post.media import MediaStore

BASE_URL = "https://example.test/media"


def _png_bytes(color: bytes = b"\x00\x00\x00") -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" + color)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _store(tmp_path, **overrides) -> MediaStore:
    kwargs = {
        "media_dir": str(tmp_path),
        "media_base_url": BASE_URL,
        "media_max_bytes": 10_000_000,
        "max_image_bytes": 5_000_000,
        "max_images_per_message": 10,
    }
    kwargs.update(overrides)
    return MediaStore(**kwargs)


def _convert(md: str, tmp_path, **store_overrides):
    return markdown_to_rich_html(md, _store(tmp_path, **store_overrides))


def test_headings_h1_h6(tmp_path):
    html, failed = _convert("# A\n\n## B\n\n### C\n\n#### D\n\n##### E\n\n###### F", tmp_path)
    assert "<h1>A</h1>" in html
    assert "<h2>B</h2>" in html
    assert "<h3>C</h3>" in html
    assert "<h4>D</h4>" in html
    assert "<h5>E</h5>" in html
    assert "<h6>F</h6>" in html
    assert failed == []


def test_bold_italic_strike(tmp_path):
    html, _ = _convert("**b** *i* ~~s~~", tmp_path)
    assert "<b>b</b>" in html
    assert "<i>i</i>" in html
    assert "<s>s</s>" in html
    assert "<strong>" not in html
    assert "<em>" not in html


def test_inline_code(tmp_path):
    html, _ = _convert("`code`", tmp_path)
    assert "<code>code</code>" in html


def test_inline_latex_math(tmp_path):
    html, failed = _convert(r"Formula $E = mc^2$ in text.", tmp_path)
    assert failed == []
    assert "<tg-math>E = mc^2</tg-math>" in html
    assert '<span class="math inline">' not in html


def test_block_latex_math(tmp_path):
    html, failed = _convert(
        "$$\n"
        r"x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}"
        "\n$$",
        tmp_path,
    )
    assert failed == []
    assert r"<tg-math-block>x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}</tg-math-block>" in html
    assert '<div class="math block">' not in html


def test_latex_math_is_html_escaped(tmp_path):
    html, failed = _convert(r"$x < y & z$", tmp_path)
    assert failed == []
    assert "<tg-math>x &lt; y &amp; z</tg-math>" in html
    assert "< y & z" not in html


def test_latex_math_does_not_capture_currency(tmp_path):
    html, failed = _convert("Price is $5 and cost is $10.", tmp_path)
    assert failed == []
    assert "<tg-math>" not in html
    assert "Price is $5 and cost is $10." in html


def test_labeled_block_latex_math_uses_telegram_tag(tmp_path):
    html, failed = _convert("$$\nx=1\n$$ (eq1)", tmp_path)
    assert failed == []
    assert "<tg-math-block>x=1</tg-math-block>" in html
    assert '<div id="eq1" class="math block">' not in html
    assert "mathlabel" not in html


def test_code_block(tmp_path):
    # language attribute spelling is PROVISIONAL (code-research §11).
    html, _ = _convert("```python\nx = 1\n```", tmp_path)
    assert "<pre>" in html
    assert "<code" in html
    assert "x = 1" in html
    assert "</code></pre>" in html


def test_blockquote(tmp_path):
    html, _ = _convert("> q", tmp_path)
    assert "<blockquote>" in html
    assert "q" in html
    assert "</blockquote>" in html


def test_unordered_list(tmp_path):
    html, _ = _convert("- a\n- b", tmp_path)
    assert "<ul>" in html
    assert "<li>a</li>" in html
    assert "<li>b</li>" in html
    assert "</ul>" in html


def test_ordered_list(tmp_path):
    html, _ = _convert("1. one\n2. two", tmp_path)
    assert "<ol>" in html
    assert "<li>one</li>" in html
    assert "<li>two</li>" in html
    assert "</ol>" in html


def test_table(tmp_path):
    # inner-cell tag spelling is PROVISIONAL (code-research §11).
    html, _ = _convert("| a | b |\n|---|---|\n| 1 | 2 |", tmp_path)
    assert "<table>" in html
    assert "</table>" in html
    assert "a" in html and "b" in html and "1" in html and "2" in html


def test_link(tmp_path):
    html, _ = _convert("[text](https://example.com)", tmp_path)
    assert '<a href="https://example.com">text</a>' in html


def test_inline_spoiler(tmp_path):
    html, failed = _convert("Text with ||secret **bold**|| inside.", tmp_path)
    assert failed == []
    assert "<tg-spoiler>secret <b>bold</b></tg-spoiler>" in html
    assert "||secret" not in html


def test_inline_spoiler_escaped_punctuation(tmp_path):
    html, failed = _convert(r"||\*not bold\* and \| pipe||", tmp_path)
    assert failed == []
    assert "<tg-spoiler>*not bold* and | pipe</tg-spoiler>" in html
    assert "< />" not in html


def test_details_container(tmp_path):
    html, failed = _convert(":::details Summary **bold**\nBody _text_.\n:::", tmp_path)
    assert failed == []
    assert "<details><summary>Summary <b>bold</b></summary>" in html
    assert "<p>Body <i>text</i>.</p>" in html
    assert "</details>" in html


def test_open_details_container(tmp_path):
    html, failed = _convert(":::details-open Open summary\nOpen body.\n:::", tmp_path)
    assert failed == []
    assert "<details open><summary>Open summary</summary>" in html
    assert "<p>Open body.</p>" in html


def test_details_summary_escaping_and_link_allowlist(tmp_path):
    html, failed = _convert(
        ":::details <script>x</script> [bad](javascript:alert(1))\nBody.\n:::", tmp_path
    )
    assert failed == []
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "<script>" not in html
    assert 'href="javascript:' not in html
    assert "[bad]" not in html


def test_details_summary_does_not_mutate_document_footnotes(tmp_path):
    html, failed = _convert(
        ":::details Summary\nBody.\n:::\n\nText[^1].\n\n[^1]: note",
        tmp_path,
    )
    assert failed == []
    assert "<summary>Summary</summary>" in html
    summary = html.split("<summary>", 1)[1].split("</summary>", 1)[0]
    assert "<footer" not in summary
    assert '<footer>1. note <a href="#footnote-ref-1">↩</a></footer>' in html


def test_footnote_reference_and_definition(tmp_path):
    html, failed = _convert("Text with note[^1].\n\n[^1]: Footnote with **bold** text.", tmp_path)
    assert failed == []
    assert '<a name="footnote-ref-1"></a><sup><a href="#footnote-1">1</a></sup>' in html
    assert (
        '<a name="footnote-1"></a><footer>1. Footnote with <b>bold</b> text. '
        '<a href="#footnote-ref-1">↩</a></footer>'
    ) in html
    assert "[^1]" not in html
    assert "<tg-reference" not in html
    assert "footnotes-list" not in html
    assert "footnote-backref" not in html


def test_inline_footnote(tmp_path):
    html, failed = _convert("Text^[Inline **note**].", tmp_path)
    assert failed == []
    assert '<a name="footnote-ref-1"></a><sup><a href="#footnote-1">1</a></sup>' in html
    assert '<a name="footnote-1"></a><footer>1. Inline <b>note</b> ' in html
    assert '<a href="#footnote-ref-1">↩</a></footer>' in html


def test_multiple_footnotes_get_stable_distinct_names(tmp_path):
    html, failed = _convert(
        "A[^a] B[^b] Again[^a].\n\n[^a]: First note.\n[^b]: Second note.",
        tmp_path,
    )
    assert failed == []
    assert html.count('href="#footnote-1"') == 2
    assert html.count('href="#footnote-2"') == 1
    assert '<a name="footnote-ref-1-2"></a><sup><a href="#footnote-1">1</a></sup>' in html
    assert '<a name="footnote-1"></a><footer>1. First note. ' in html
    assert '<footer>1. First note. <a href="#footnote-ref-1">↩</a></footer>' in html
    assert '<a name="footnote-2"></a><footer>2. Second note. ' in html
    assert '<footer>2. Second note. <a href="#footnote-ref-2">↩</a></footer>' in html


def test_footnote_body_keeps_escaping_and_link_allowlist(tmp_path):
    html, failed = _convert(
        "Text[^evil].\n\n[^evil]: <script>x</script> [bad](javascript:alert(1))",
        tmp_path,
    )
    assert failed == []
    assert "<footer>1. " in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "<script>" not in html
    assert 'href="javascript:' not in html


def test_footnote_body_does_not_emit_block_or_media_tags(tmp_path):
    html, failed = _convert(
        "Text[^1].\n\n"
        "[^1]: Intro.\n\n"
        "    - item **bold**\n"
        "    - second\n\n"
        "    ![alt](https://img.example.com/p.png)\n\n"
        "    | a | b |\n"
        "    |---|---|\n"
        "    | 1 | 2 |\n\n"
        "    # Heading",
        tmp_path,
    )
    assert failed == []
    footer = html.split("<footer>1. ", 1)[1].split("</footer>", 1)[0]
    assert "Intro." in footer
    assert "item <b>bold</b>" in footer
    assert "second" in footer
    assert "alt" in footer
    assert "Heading" in footer
    assert "a" in footer and "b" in footer and "1" in footer and "2" in footer
    assert not any(
        tag in footer
        for tag in (
            "<h1",
            "</h1",
            "<h2",
            "</h2",
            "<h3",
            "</h3",
            "<p",
            "<ul",
            "<ol",
            "<li",
            "<table",
            "<details",
            "<thead",
            "<tbody",
            "<tr",
            "<th",
            "<td",
            "<img",
            "<blockquote",
            "<pre",
        )
    )


def test_details_inside_footnote_does_not_emit_block_tags(tmp_path):
    html, failed = _convert(
        "Text[^1].\n\n[^1]: Intro.\n\n    :::details S\n    Hidden **body**.\n    :::",
        tmp_path,
    )
    assert failed == []
    footer = html.split("<footer>1. ", 1)[1].split("</footer>", 1)[0]
    assert "Intro." in footer
    assert "S" in footer
    assert "Hidden <b>body</b>." in footer
    assert "<details" not in footer
    assert "<summary" not in footer


def test_external_image_passthrough(tmp_path):
    html, failed = _convert("![alt](https://img.example.com/p.png)", tmp_path)
    assert '<img src="https://img.example.com/p.png"' in html
    assert failed == []
    # media store not touched for external images
    assert list(tmp_path.iterdir()) == []


def test_external_gif_renders_as_video_without_download(tmp_path):
    html, failed = _convert("![animation](https://cdn.example.com/a.gif)", tmp_path)
    assert '<video src="https://cdn.example.com/a.gif"></video>' in html
    assert "<img" not in html
    assert failed == []
    assert list(tmp_path.iterdir()) == []


def test_external_video_formats_render_as_video(tmp_path):
    for ext in ("mp4", "mov", "m4v", "webm"):
        html, failed = _convert(f"![video](https://cdn.example.com/clip.{ext})", tmp_path)
        assert f'<video src="https://cdn.example.com/clip.{ext}"></video>' in html
        assert failed == []


def test_external_media_extensions_are_case_insensitive(tmp_path):
    html, failed = _convert("![video](https://cdn.example.com/CLIP.MP4)", tmp_path)
    assert '<video src="https://cdn.example.com/CLIP.MP4"></video>' in html
    assert failed == []


def test_external_audio_formats_render_as_audio(tmp_path):
    for ext in ("mp3", "ogg", "oga", "m4a", "aac", "wav", "flac"):
        html, failed = _convert(f"![audio](https://cdn.example.com/track.{ext})", tmp_path)
        assert f'<audio src="https://cdn.example.com/track.{ext}"></audio>' in html
        assert failed == []


def test_external_iphone_photo_formats_render_as_image(tmp_path):
    for ext in ("heic", "heif"):
        html, failed = _convert(f"![photo](https://cdn.example.com/photo.{ext})", tmp_path)
        assert f'<img src="https://cdn.example.com/photo.{ext}" />' in html
        assert failed == []


def test_external_media_type_uses_path_extension_not_query_or_fragment(tmp_path):
    html, failed = _convert(
        "![bad](https://cdn.example.com/file?name=clip.mp4)\n\n"
        "![bad](https://cdn.example.com/file.svg?name=photo.png)\n\n"
        "![ok](https://cdn.example.com/video.mp4?token=abc#frag)",
        tmp_path,
    )
    assert '<video src="https://cdn.example.com/video.mp4?token=abc#frag"></video>' in html
    assert "file?name=clip.mp4" not in html
    assert "file.svg?name=photo.png" not in html
    assert failed == [0, 1]


def test_external_dangerous_media_extensions_are_rejected(tmp_path):
    md = "\n\n".join(
        f"![bad](https://cdn.example.com/file.{ext})"
        for ext in ("svg", "html", "htm", "pdf", "exe", "js", "zip", "m3u8", "mpd")
    )
    html, failed = _convert(md, tmp_path)
    assert "<img" not in html
    assert "<video" not in html
    assert "<audio" not in html
    assert "cdn.example.com" not in html
    assert failed == list(range(9))


def test_external_media_rejects_malformed_urls(tmp_path):
    md = "\n\n".join(
        (
            "![bad](//cdn.example.com/video.mp4)",
            "![bad](https://user:pass@cdn.example.com/video.mp4)",
            "![bad](https://cdn.example.com\\evil/video.mp4)",
            "![bad](file:///tmp/video.mp4)",
        )
    )
    html, failed = _convert(md, tmp_path)
    assert "<video" not in html
    assert "cdn.example.com" not in html
    assert failed == [0, 1, 2, 3]


def test_external_media_caption_is_escaped(tmp_path):
    html, failed = _convert(
        '![video](https://cdn.example.com/clip.mp4 "Caption <script>alert(1)</script>")',
        tmp_path,
    )
    assert failed == []
    assert "<p><figure>" not in html
    assert '<figure><video src="https://cdn.example.com/clip.mp4"></video>' in html
    assert "<figcaption>Caption &lt;script&gt;alert(1)&lt;/script&gt;</figcaption></figure>" in html
    assert "<script>" not in html


def test_external_media_src_is_escaped(tmp_path):
    html, failed = _convert("![video](https://cdn.example.com/clip.mp4?a=1&b=2)", tmp_path)
    assert failed == []
    assert '<video src="https://cdn.example.com/clip.mp4?a=1&amp;b=2"></video>' in html
    assert 'src="https://cdn.example.com/clip.mp4?a=1&b=2"' not in html


def test_external_media_renders_inside_nested_block_contexts(tmp_path):
    html, failed = _convert(
        "> ![quote video](https://cdn.example.com/quote.mp4)\n\n"
        "- ![list audio](https://cdn.example.com/list.mp3)\n\n"
        ":::details Media\n"
        "![details gif](https://cdn.example.com/details.gif)\n"
        ":::",
        tmp_path,
    )
    assert failed == []
    assert '<video src="https://cdn.example.com/quote.mp4"></video>' in html
    assert '<li><video src="https://cdn.example.com/list.mp3"></video>' not in html
    assert '<audio src="https://cdn.example.com/list.mp3"></audio>' in html
    assert '<video src="https://cdn.example.com/details.gif"></video>' in html


def test_external_media_limit_is_enforced(tmp_path):
    md = "\n\n".join(f"![v](https://cdn.example.com/{i}.mp4)" for i in range(51))
    html, failed = _convert(md, tmp_path)
    assert html.count("<video") == 50
    assert failed == [50]


def test_external_media_limit_checked_before_saving_base64_image(tmp_path):
    png = _png_bytes()
    b64 = _b64(png)
    md = "\n\n".join(f"![v](https://cdn.example.com/{i}.mp4)" for i in range(50))
    md += f"\n\n![over](data:image/png;base64,{b64})"
    html, failed = _convert(md, tmp_path)
    assert html.count("<video") == 50
    assert "<img" not in html
    assert failed == [50]
    assert list(tmp_path.iterdir()) == []


def test_external_media_inside_text_degrades_to_alt_text(tmp_path):
    html, failed = _convert(
        "Before ![video alt](https://cdn.example.com/clip.mp4) after.", tmp_path
    )
    assert "<video" not in html
    assert "https://cdn.example.com" not in html
    assert "Before video alt after." in html
    assert failed == []


def test_external_media_inside_table_does_not_emit_media_tag(tmp_path):
    html, failed = _convert(
        "| media |\n|---|\n| ![audio alt](https://cdn.example.com/track.mp3) |",
        tmp_path,
    )
    assert "<audio" not in html
    assert "https://cdn.example.com" not in html
    assert "audio alt" in html
    assert failed == []


def test_reference_base64_image_hosted(tmp_path):
    import hashlib

    png = _png_bytes()
    b64 = _b64(png)
    md = f"![][image1]\n\n[image1]: <data:image/png;base64,{b64}>"
    html, failed = _convert(md, tmp_path)
    digest = hashlib.sha256(png).hexdigest()
    assert f'<img src="{BASE_URL}/{digest}.png"' in html
    assert failed == []
    assert "data:" not in html


def test_raw_html_block_escaped(tmp_path):
    # html=False: a raw HTML block in the source must be escaped, not passed through.
    html, _ = _convert("<script>alert(1)</script>\n\nHello", tmp_path)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Hello" in html


def test_inline_html_in_link_text_escaped(tmp_path):
    # Inline HTML inside link text must also be escaped under html=False.
    html, _ = _convert("[<b>x</b>](https://example.com)", tmp_path)
    assert "&lt;b&gt;" in html
    # the only <b> tags allowed are ones the renderer constructs from **strong**
    assert "<b>x</b>" not in html


def test_text_node_escaping(tmp_path):
    html, _ = _convert('a < b & c > d "q"', tmp_path)
    assert "&lt;" in html
    assert "&gt;" in html
    assert "&amp;" in html
    assert "a &lt; b" in html  # literal < escaped in place, not interpreted as a tag
    assert "<b>" not in html


def test_code_block_escaping(tmp_path):
    html, _ = _convert('```\n<a> & "x"\n```', tmp_path)
    assert "&lt;a&gt;" in html
    assert "&amp;" in html


def test_attribute_value_escaping(tmp_path):
    # A quote/angle inside a link destination must not break out of the attribute.
    html, _ = _convert('[t](https://e.com/?a="1"&b=<2>)', tmp_path)
    assert 'href="https://e.com/?a=' in html
    # raw unescaped double-quote must not appear inside the attribute value
    assert '"1"' not in html
    assert "&quot;" in html or "%22" in html


def test_javascript_scheme_rejected_link(tmp_path):
    # No anchor is produced; the disallowed scheme never lands in an href attr.
    html, _ = _convert("[x](javascript:alert(1))", tmp_path)
    assert 'href="javascript:' not in html
    assert "<a " not in html
    assert "<a>" not in html


def test_javascript_scheme_rejected_image(tmp_path):
    # A javascript: image src is dropped at parse time — no <img>, no scheme attr.
    html, _ = _convert("![x](javascript:alert(1))", tmp_path)
    assert 'src="javascript:' not in html
    assert "<img" not in html


def test_data_scheme_rejected_for_href(tmp_path):
    # data: survives parse (so base64 images work) but link_open rejects it for hrefs.
    html, _ = _convert("[x](data:text/html;base64,PHNjcmlwdD4=)", tmp_path)
    assert 'href="data:' not in html
    assert "<a " not in html
    assert "<a>" not in html
    # link text is preserved
    assert "x" in html


def test_failed_media_indices_ordered(tmp_path):
    # 3 images: #1 (bad base64) fails, #2 ok, #3 (svg) fails -> [0, 2]
    good = _b64(_png_bytes(color=b"\x10\x20\x30"))
    svg = _b64(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    md = (
        "![][a]\n\n![][b]\n\n![][c]\n\n"
        "[a]: <data:image/png;base64,@@notbase64@@>\n"
        f"[b]: <data:image/png;base64,{good}>\n"
        f"[c]: <data:image/svg+xml;base64,{svg}>"
    )
    html, failed = _convert(md, tmp_path)
    assert failed == [0, 2]
    # the good middle image still produced an <img>
    assert html.count("<img") == 1


def test_paragraphs_separated_by_spacer_block(tmp_path):
    # Rich Messages collapse whitespace between block tags, so a visually-empty
    # spacer paragraph <p>&nbsp;</p> is injected between adjacent top-level
    # paragraphs to restore the owner's blank-line separation.
    html, failed = _convert("Параграф один.\n\nПараграф два.\n\nПараграф три.", tmp_path)
    assert html == (
        "<p>Параграф один.</p>\n<p>&nbsp;</p><p>Параграф два.</p>\n"
        "<p>&nbsp;</p><p>Параграф три.</p>\n"
    )
    assert failed == []
    # spacer is the literal entity, never double-escaped
    assert "&amp;nbsp;" not in html


def test_list_items_get_no_spacer(tmp_path):
    # The spacer rule fires only for top-level paragraphs, never inside a list.
    html, _ = _convert("- a\n- b", tmp_path)
    assert html == "<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n"
    assert "&nbsp;" not in html


def test_code_block_followed_by_paragraph_gets_no_spacer(tmp_path):
    # Only paragraph→paragraph adjacency gets a spacer; a code block followed by a
    # paragraph must not (the client already spaces non-paragraph blocks).
    html, _ = _convert("```\nx = 1\n```\n\nafter", tmp_path)
    assert "</code></pre>\n<p>after</p>" in html
    assert "&nbsp;" not in html
    assert html.endswith("<p>after</p>\n")


def test_indented_code_block_followed_by_paragraph_gets_no_spacer(tmp_path):
    html, _ = _convert("    x = 1\n\nafter", tmp_path)
    assert "</code></pre>\n<p>after</p>" in html
    assert "&nbsp;" not in html


def test_heading_followed_by_paragraph_gets_spacer(tmp_path):
    # A top-level heading must not glue to the paragraph under it: a spacer goes
    # before the text paragraph that follows a heading.
    html, _ = _convert("## Title\n\nПервый абзац.", tmp_path)
    assert html == "<h2>Title</h2>\n<p>&nbsp;</p><p>Первый абзац.</p>\n"
    assert "&amp;nbsp;" not in html


def test_paragraph_followed_by_heading_gets_no_spacer(tmp_path):
    # The client already gaps before a heading — never insert a spacer before one,
    # or it doubles. (Spacer only goes before a *text paragraph*.)
    html, _ = _convert("Абзац.\n\n## Title", tmp_path)
    assert html == "<p>Абзац.</p>\n<h2>Title</h2>\n"
    assert "&nbsp;" not in html


def test_heading_followed_by_hr_gets_spacer(tmp_path):
    html, _ = _convert("## Title\n\n---", tmp_path)
    assert html == "<h2>Title</h2>\n<p>&nbsp;</p><hr />\n"


def test_paragraph_followed_by_hr_gets_spacer(tmp_path):
    html, _ = _convert("Абзац.\n\n---", tmp_path)
    assert html == "<p>Абзац.</p>\n<p>&nbsp;</p><hr />\n"


def test_hr_followed_by_paragraph_gets_spacer(tmp_path):
    html, _ = _convert("---\n\nАбзац.", tmp_path)
    assert html == "<hr />\n<p>&nbsp;</p><p>Абзац.</p>\n"


def test_hr_followed_by_heading_gets_spacer(tmp_path):
    html, _ = _convert("---\n\n## Title", tmp_path)
    assert html == "<hr />\n<p>&nbsp;</p><h2>Title</h2>\n"


def test_image_only_paragraph_no_spacer_before_or_after(tmp_path):
    # A media-only paragraph is not a text paragraph: it gets no spacer before it,
    # and the text paragraph after it gets none either (image-para is not a
    # "preceding text paragraph").
    html, _ = _convert(
        "Текст.\n\n![alt](https://img.example.com/p.png)\n\nИли вот табличка.",
        tmp_path,
    )
    assert html == (
        "<p>Текст.</p>\n"
        '<p><img src="https://img.example.com/p.png" /></p>\n'
        "<p>Или вот табличка.</p>\n"
    )
    assert "&nbsp;" not in html


def test_table_followed_by_paragraph_gets_no_spacer(tmp_path):
    # A table is not heading/paragraph — the paragraph after it gets no spacer.
    html, _ = _convert("| a | b |\n|---|---|\n| 1 | 2 |\n\nПосле таблицы.", tmp_path)
    assert "</table>\n<p>После таблицы.</p>" in html
    assert "&nbsp;" not in html


def test_mixed_document_spacer_only_between_text_paragraphs_and_after_headings(tmp_path):
    # Spacer fires ONLY before a text paragraph preceded by a heading or another
    # text paragraph. Image-only paragraphs, tables, lists, blockquotes never
    # trigger or receive a spacer.
    md = (
        "# Заголовок\n\n"
        "Первый абзац.\n\n"
        "- item1\n- item2\n\n"
        "> quote\n\n"
        "![alt](https://img.example.com/p.png)\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "Второй абзац.\n\n"
        "Третий абзац."
    )
    html, failed = _convert(md, tmp_path)
    assert failed == []
    # heading→text-paragraph: spacer
    assert "<h1>Заголовок</h1>\n<p>&nbsp;</p><p>Первый абзац.</p>" in html
    # text-paragraph→list: NO spacer (list is not a text paragraph)
    assert "<p>Первый абзац.</p>\n<ul>" in html
    # image-paragraph→table: NO spacer
    assert "</p>\n<table>" in html
    # table→text-paragraph: NO spacer (table is not heading/paragraph)
    assert "</table>\n<p>Второй абзац.</p>" in html
    # text-paragraph→text-paragraph: spacer
    assert "<p>Второй абзац.</p>\n<p>&nbsp;</p><p>Третий абзац.</p>" in html
    # exactly one spacer in the whole doc (heading→para + para→para = 2)
    assert html.count("<p>&nbsp;</p>") == 2
    # exactly one terminating newline
    assert html.endswith("</p>\n")
