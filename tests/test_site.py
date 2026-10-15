"""The static site is a faithful, escaped reading copy of the committed evidence."""

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    # Registered first: dataclasses resolve the module's annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


site = _load_script()


def test_index_links_every_page(tmp_path):
    written = site.build(tmp_path)
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    hrefs = set(re.findall(r'href="([^"]+)"', index))
    pages = [page.output for page in (*site.PAGES, *site.COPIED)]
    assert len(pages) == 5
    for name in pages:
        assert name in hrefs
        assert (tmp_path / name).is_file()
    assert sorted(path.name for path in written) == sorted(["index.html", *pages])


def test_robustness_report_is_copied_byte_identical(tmp_path):
    site.build(tmp_path)
    source = ROOT / "examples" / "adversarial-robustness-report.html"
    assert (tmp_path / "adversarial-robustness-report.html").read_bytes() == source.read_bytes()


def test_rendered_pages_turn_pipe_tables_into_tables(tmp_path):
    site.build(tmp_path)
    for page in site.PAGES:
        rendered = (tmp_path / page.output).read_text(encoding="utf-8")
        assert "<table>" in rendered, page.source
        assert not re.search(r"^\|", rendered, re.MULTILINE), page.source
        assert 'href="index.html"' in rendered


def test_build_is_deterministic(tmp_path):
    first = {p.name: p.read_bytes() for p in site.build(tmp_path / "a")}
    second = {p.name: p.read_bytes() for p in site.build(tmp_path / "b")}
    assert first == second


def test_html_in_source_text_is_escaped():
    rendered = site.render_markdown(
        "# Title <script>alert(1)</script>\n\n"
        "Text with <b>tags</b> & `<code>` and **bold <i>**.\n\n"
        "| a | b |\n|---|---:|\n| <img src=x onerror=alert(1)> | 1 |\n\n"
        "- item <em>raw</em>\n\n"
        "```\n<div>fenced</div>\n```\n"
    )
    assert "<script>" not in rendered and "&lt;script&gt;" in rendered
    assert "<b>" not in rendered and "&lt;b&gt;tags&lt;/b&gt; &amp;" in rendered
    assert "<code>&lt;code&gt;</code>" in rendered
    assert "<strong>bold &lt;i&gt;</strong>" in rendered
    assert "<img" not in rendered and "&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "<li>item &lt;em&gt;raw&lt;/em&gt;</li>" in rendered
    assert "<pre><code>&lt;div&gt;fenced&lt;/div&gt;</code></pre>" in rendered
    assert '<td style="text-align: right">1</td>' in rendered


def test_links_render_but_unsafe_schemes_do_not():
    rendered = site.render_markdown(
        "[docs](https://example.com/a?b=1&c=2) and [bad](javascript:alert(1)) "
        'and [quote](x"onmouseover="y)'
    )
    assert '<a href="https://example.com/a?b=1&amp;c=2">docs</a>' in rendered
    assert "javascript:" not in rendered.split("bad")[0] and 'href="javascript' not in rendered
    assert 'onmouseover="' not in rendered


def test_inline_formatting_leaves_identifiers_alone():
    rendered = site.render_markdown("Scores like clause_f1 and *emphasis* and _also_ here.")
    assert "clause_f1" in rendered
    assert "<em>emphasis</em>" in rendered and "<em>also</em>" in rendered
