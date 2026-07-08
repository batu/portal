import json
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

from gallery import cli, client as gallery_client, db, server


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def tiny_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfabd4000000"
        "0049454e44ae426082"
    )


def content_disposition_type(response) -> str:
    return response.headers.get("content-disposition", "").split(";", 1)[0].strip().lower()


def assert_report_html_inline(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox allow-same-origin"
    assert "allow-scripts" not in response.headers["content-security-policy"]
    assert content_disposition_type(response) != "attachment"


def assert_html_attachment(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in response.headers
    assert content_disposition_type(response) == "attachment"


class IsoClock:
    def __init__(self):
        self.current = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        value = self.current
        self.current += timedelta(seconds=1)
        return value.isoformat()


def install_testclient_adapter(monkeypatch, test_client, before_request=None):
    def testclient_request(method, url, headers, data=None):
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        if before_request is not None:
            before_request(method, path)
        response = test_client.request(method, path, headers=headers, content=data)
        if response.status_code >= 400:
            detail = response.text
            try:
                parsed_detail = response.json()
                detail = parsed_detail.get("detail", detail) if isinstance(parsed_detail, dict) else detail
            except json.JSONDecodeError:
                pass
            raise gallery_client.GalleryClientError(response.status_code, detail)
        return response.json() if response.content else {}

    monkeypatch.setattr(gallery_client, "_request", testclient_request)


def test_portal_inbox_cli_browser_twins_rendering_and_closed_streams(client, token, monkeypatch, capsys):
    slug = "phase23-inbox-e2e"
    question_text = "Which rollout should I assume?"
    answer_text = "Assume the cookie twin path is correct."
    note_text = "Please review the queued steering note next turn."
    rendered_pages = {}
    answer_posted = False

    def answer_before_reply_poll(method, path):
        nonlocal answer_posted
        if answer_posted:
            return
        if method != "GET" or not path.startswith(f"/api/streams/{slug}/messages?"):
            return
        parsed_query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        if parsed_query.get("direction") != ["to_agent"] or parsed_query.get("unconsumed") != ["1"]:
            return
        answer_posted = True
        stream = db.get_stream(slug)
        assert stream is not None
        questions = db.list_messages(stream["id"], direction="to_human")
        assert [message["text"] for message in questions] == [question_text]
        question = questions[0]

        unanswered = client.get(f"/s/{slug}?token={token}")
        assert unanswered.status_code == 200
        rendered_pages["unanswered"] = unanswered.text
        assert question_text in unanswered.text
        assert "Agent asks" in unanswered.text
        assert 'method="post" action="/s/phase23-inbox-e2e/answer"' in unanswered.text
        assert f'value="{question["id"]}"' in unanswered.text
        assert "data-stream-note-form" in unanswered.text
        assert "token=" not in unanswered.text
        assert token not in unanswered.text

        answer = client.post(
            f"/s/{slug}/answer",
            json={"text": answer_text, "question_id": question["id"]},
        )
        assert answer.status_code == 200
        assert answer.json()["direction"] == "to_agent"
        assert answer.json()["text"] == answer_text

        answered_queued = client.get(f"/s/{slug}")
        assert answered_queued.status_code == 200
        rendered_pages["answered_queued"] = answered_queued.text
        assert "Answered questions" in answered_queued.text
        assert question_text in answered_queued.text
        assert answer_text in answered_queued.text
        assert '<span class="status-badge queued">queued</span>' in answered_queued.text
        assert f'value="{question["id"]}"' not in answered_queued.text
        assert "token=" not in answered_queued.text
        assert token not in answered_queued.text

    install_testclient_adapter(monkeypatch, client, before_request=answer_before_reply_poll)
    monkeypatch.setattr(cli.config, "client_config", lambda: ("http://portal.test", token))
    monkeypatch.setattr(db, "now_iso", IsoClock())
    notifications = []
    monkeypatch.setattr(
        server,
        "_notify_to_human_message",
        lambda notified_slug, text: notifications.append((notified_slug, text)),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "ask", "--stream", slug, "--timeout", "1", "--interval", "1", question_text],
    )

    cli.main()

    ask_output = json.loads(capsys.readouterr().out)
    assert ask_output["reply"] == answer_text
    assert ask_output["message_id"].startswith("m_")
    assert ask_output["elapsed_s"] >= 0
    assert ask_output["elapsed_s"] < 1
    assert notifications == [(slug, question_text)]

    after_ask = client.get(f"/s/{slug}")
    assert after_ask.status_code == 200
    rendered_pages["answer_picked_up"] = after_ask.text
    assert answer_text in after_ask.text
    assert '<span class="status-badge picked-up">picked up</span>' in after_ask.text
    assert "token=" not in after_ask.text
    assert token not in after_ask.text

    note = client.post(f"/s/{slug}/note", json={"text": note_text})
    assert note.status_code == 200
    assert note.json()["direction"] == "to_agent"
    assert note.json()["text"] == note_text
    assert notifications == [(slug, question_text)]

    note_queued = client.get(f"/s/{slug}")
    assert note_queued.status_code == 200
    rendered_pages["note_queued"] = note_queued.text
    assert note_text in note_queued.text
    assert '<span class="status-badge queued">queued</span>' in note_queued.text
    assert "token=" not in note_queued.text
    assert token not in note_queued.text

    monkeypatch.setattr("sys.argv", ["portal", "pull", "--stream", slug])

    cli.main()

    pull_output = json.loads(capsys.readouterr().out)
    assert pull_output == {"text": note_text, "message_id": note.json()["id"]}

    after_pull = client.get(f"/s/{slug}")
    assert after_pull.status_code == 200
    rendered_pages["note_picked_up"] = after_pull.text
    assert note_text in after_pull.text
    assert '<span class="status-badge picked-up">picked up</span>' in after_pull.text
    assert "token=" not in after_pull.text
    assert token not in after_pull.text

    stream = db.get_stream(slug)
    closed_question = db.create_message(stream["id"], "to_human", "Closed question still readable")
    closed_note = db.create_message(stream["id"], "to_agent", "Closed note still readable")
    close = client.post(f"/api/streams/{slug}/close", headers=auth_headers(token))
    assert close.status_code == 200

    closed_page = client.get(f"/s/{slug}")
    assert closed_page.status_code == 200
    rendered_pages["archived"] = closed_page.text
    assert "Archived stream. Posts and decisions are read-only." in closed_page.text
    assert "Closed question still readable" in closed_page.text
    assert "Closed note still readable" in closed_page.text
    assert "data-stream-note-form" not in closed_page.text
    assert "data-answer-form" not in closed_page.text
    assert "token=" not in closed_page.text
    assert token not in closed_page.text

    rejected_note = client.post(f"/s/{slug}/note", json={"text": "Too late"})
    rejected_answer = client.post(
        f"/s/{slug}/answer",
        json={"text": "Too late", "question_id": closed_question["id"]},
    )
    assert rejected_note.status_code == 409
    assert rejected_answer.status_code == 409

    monkeypatch.setattr("sys.argv", ["portal", "ask", "--stream", slug, "Too late?"])
    with pytest.raises(SystemExit) as ask_exc:
        cli.main()
    ask_error = capsys.readouterr()
    assert ask_exc.value.code == 1
    assert ask_error.out == ""
    assert "error: HTTP 409: stream is closed:" in ask_error.err

    monkeypatch.setattr("sys.argv", ["portal", "pull", "--stream", slug])
    with pytest.raises(SystemExit) as pull_exc:
        cli.main()
    pull_error = capsys.readouterr()
    assert pull_exc.value.code == 1
    assert pull_error.out == ""
    assert "error: HTTP 409: stream is closed:" in pull_error.err
    assert closed_note["id"] in {message["id"] for message in db.list_messages(stream["id"], unconsumed=True)}

    assert set(rendered_pages) == {
        "unanswered",
        "answered_queued",
        "answer_picked_up",
        "note_queued",
        "note_picked_up",
        "archived",
    }


def test_portal_inbox_media_header_regressions(client, token):
    slug = "phase23-media-e2e"
    report = client.post(
        f"/api/streams/{slug}/posts",
        headers=auth_headers(token),
        data={
            "type": "report",
            "title": "Inbox E2E report",
            "author": "codex",
            "body": json.dumps({"summary": "report HTML stays inline"}),
        },
        files=[
            (
                "files",
                (
                    "report.html",
                    b"<html><body><h1>Inline report</h1></body></html>",
                    "text/html",
                ),
            )
        ],
    )
    assert report.status_code == 200
    report_post = report.json()["post"]
    report_media_path = report_post["body"]["files"][0]["media_path"]

    client.get(f"/s/{slug}?token={token}")
    report_page = client.get(f"/s/{slug}")
    assert report_page.status_code == 200
    assert f'src="/media/{report_post["id"]}/{report_media_path}"' in report_page.text
    assert 'sandbox="allow-same-origin"' in report_page.text
    assert "allow-scripts" not in report_page.text
    assert "token=" not in report_page.text
    assert token not in report_page.text

    report_media = client.get(f"/media/{report_post['id']}/{report_media_path}")
    assert_report_html_inline(report_media)
    assert b"Inline report" in report_media.content

    request = client.post(
        "/api/requests",
        headers=auth_headers(token),
        data={
            "title": "Inbox E2E HTML variant",
            "kind": "pick-one",
            "project": "portal/phase23-media-e2e",
        },
        files=[
            ("files", ("safe.png", tiny_png_bytes(), "image/png")),
            (
                "files",
                (
                    "variant.html",
                    b"<html><body><h1>Attachment variant</h1></body></html>",
                    "text/html",
                ),
            ),
        ],
    )
    assert request.status_code == 200
    req_id = request.json()["id"]
    detail = client.get(f"/api/requests/{req_id}", headers=auth_headers(token))
    assert detail.status_code == 200
    html_variant_path = detail.json()["variants"][1]["media_path"]
    html_variant = client.get(f"/media/{req_id}/{html_variant_path}")
    assert_html_attachment(html_variant)

    decision = client.post(
        f"/api/streams/{slug}/posts",
        headers=auth_headers(token),
        data={
            "type": "decision",
            "title": "Decision post HTML attachment",
            "author": "codex",
            "body": json.dumps({"request_id": req_id}),
        },
        files=[
            (
                "files",
                (
                    "decision.html",
                    b"<html><body><h1>Decision attachment</h1></body></html>",
                    "text/html",
                ),
            )
        ],
    )
    assert decision.status_code == 200
    decision_post = decision.json()["post"]
    decision_media_path = decision_post["body"]["files"][0]["media_path"]
    decision_media = client.get(f"/media/{decision_post['id']}/{decision_media_path}")
    assert_html_attachment(decision_media)
