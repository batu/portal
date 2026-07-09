"""Stored-XSS regression tests for the rendered request context.

These exercise the real `/r/{req_id}` render path (Markdown -> sanitizer ->
`context_html|safe` sink), not just the sanitizer helper in isolation.
"""

import pytest

from gallery.server import _sanitize_context_html


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def tiny_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfabd4000000"
        "0049454e44ae426082"
    )


def _create_request(client, token, context):
    resp = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={
            "title": "context xss probe",
            "kind": "comment",
            "project": "sec/xss",
            "context": context,
        },
        files=[("files", ("variant.png", tiny_png_bytes(), "image/png"))],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _render(client, token, context):
    req_id = _create_request(client, token, context)
    page = client.get(f"/r/{req_id}?token={token}")
    assert page.status_code == 200
    return page


XSS_PAYLOADS = [
    "<script>window.__xss=1</script>",
    "<img src=x onerror=alert(1)>",
    '<a href="javascript:alert(1)">click</a>',
    "[click](javascript:alert(1))",
    '<a href="JaVaScRiPt:alert(1)">mixed case</a>',
    "<a href=\"java\tscript:alert(1)\">tab obfuscated</a>",
    '<a href="data:text/html,<script>alert(1)</script>">data uri</a>',
    '<img src="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">',
    "<svg><script>alert(1)</script></svg>",
    "<svg onload=alert(1)></svg>",
    '<math><mtext><script>alert(1)</script></mtext></math>',
    "<iframe src=javascript:alert(1)></iframe>",
    "<body onload=alert(1)>",
    "<div onclick=alert(1)>x</div>",
    "<a href=vbscript:alert(1)>x</a>",
    "<p><scr<script>ipt>alert(1)</script></p>",  # malformed / nested
    "<style>body{background:url(javascript:alert(1))}</style>",
]


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_request_page_never_renders_executable_markup(client, token, payload):
    page = _render(client, token, payload)
    body = page.text
    # Locate the sanitized context block so we only assert against the injected
    # region, not unrelated page chrome (base.html itself loads a <script>).
    # An absent block means the payload was stripped to nothing — also safe.
    if '<div class="context">' in body:
        context_block = body.split('<div class="context">', 1)[1].split("</div>", 1)[0]
    else:
        context_block = ""

    lowered = context_block.lower()
    assert "<script" not in lowered
    assert "javascript:" not in lowered
    assert "vbscript:" not in lowered
    assert "onerror" not in lowered
    assert "onload" not in lowered
    assert "onclick" not in lowered
    assert "<iframe" not in lowered
    assert "<svg" not in lowered
    assert "<style" not in lowered
    assert "data:text/html" not in lowered


def test_request_page_preserves_expected_markdown(client, token):
    context = (
        "# Heading\n\n"
        "Some **bold** and *italic* text with `inline code`.\n\n"
        "- first\n- second\n\n"
        "[docs](https://example.com/docs)\n\n"
        "> a quote\n"
    )
    page = _render(client, token, context)
    body = page.text
    context_block = body.split('<div class="context">', 1)[1].split("</div>", 1)[0]

    assert "<h1>Heading</h1>" in context_block
    assert "<strong>bold</strong>" in context_block
    assert "<em>italic</em>" in context_block
    assert "<code>inline code</code>" in context_block
    assert "<li>first</li>" in context_block
    assert '<a href="https://example.com/docs">docs</a>' in context_block
    assert "<blockquote>" in context_block


def test_request_page_sets_restrictive_csp(client, token):
    page = _render(client, token, "hello")
    csp = page.headers.get("content-security-policy", "")
    assert "default-src 'none'" in csp
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp
    assert "frame-ancestors 'none'" in csp


def test_sanitizer_keeps_safe_relative_and_mailto_links():
    out = _sanitize_context_html(
        '<a href="/media/x.png">rel</a> '
        '<a href="mailto:a@b.com">mail</a> '
        '<a href="#anchor">frag</a>'
    )
    assert '<a href="/media/x.png">rel</a>' in out
    assert '<a href="mailto:a@b.com">mail</a>' in out
    assert '<a href="#anchor">frag</a>' in out


def test_sanitizer_escapes_stray_text_angle_brackets():
    # Raw script text that is dropped as a tag must never reappear un-escaped.
    out = _sanitize_context_html("5 < 3 and <script>bad()</script> tail")
    assert "<script" not in out.lower()
    assert "bad()" not in out
    assert "&lt; 3" in out
    assert out.endswith(" tail")


@pytest.mark.parametrize(
    ("html_text", "expected"),
    [
        (
            '<p><a href="https://example.com">unclosed link</p>',
            '<p><a href="https://example.com">unclosed link</a></p>',
        ),
        (
            "<p><strong><em>unclosed formatting</p>",
            "<p><strong><em>unclosed formatting</em></strong></p>",
        ),
        (
            "<blockquote><ul><li>unclosed list",
            "<blockquote><ul><li>unclosed list</li></ul></blockquote>",
        ),
        (
            "<a><strong>crossed tags</a> tail</strong>",
            "<a><strong>crossed tags</strong></a> tail",
        ),
        ("<a/>self-closing link", "<a></a>self-closing link"),
    ],
)
def test_sanitizer_balances_allowed_tags(html_text, expected):
    assert _sanitize_context_html(html_text) == expected


def test_unclosed_context_link_cannot_wrap_trusted_request_controls(client, token):
    page = _render(client, token, '<a href="https://attacker.example">captured')
    body = page.text
    context_start = body.index('<div class="context">')
    link_close = body.index("</a>", context_start)
    context_close = body.index("</div>", context_start)
    variant_grid = body.index('<div class="variant-grid"', context_start)
    decide_button = body.index('id="decide-btn"', context_start)

    assert link_close < context_close < variant_grid < decide_button


def test_balancing_keeps_attribute_and_url_filtering_intact():
    out = _sanitize_context_html(
        '<a href="javascript:alert(1)" onclick="alert(2)" title="safe">link'
        '<img src="data:text/html,bad" onerror="alert(3)" alt="safe">'
    )

    assert out == '<a title="safe">link<img alt="safe"></a>'
