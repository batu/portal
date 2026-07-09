import json
import urllib.error
import urllib.parse
from io import BytesIO
from pathlib import Path

import pytest

from gallery import cli, client as gallery_client, trello_watch


BOARD_ID = "board-1"
TODO_ID = "list-todo"
WORKED_ID = "list-worked"
MAX_ID = "list-max"
BLOCKED_ID = "list-blocked"


def write_repo(tmp_path, lists=None):
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    config = {
        "trello": {
            "board_id": BOARD_ID,
            "board_name": "scratch",
            "lists": lists
            or {
                "todo": TODO_ID,
                "worked": WORKED_ID,
                "aesthetics_reviewed": MAX_ID,
                "blocked_on_batu": BLOCKED_ID,
            },
        }
    }
    (repo / "agents" / "config.json").write_text(json.dumps(config))
    return repo


def card(card_id="card-1", short="08KM8i8Q", name="Build it", list_id=TODO_ID, **overrides):
    payload = {
        "id": card_id,
        "shortLink": short,
        "name": name,
        "idList": list_id,
        "idBoard": BOARD_ID,
        "closed": False,
        "url": f"https://trello.com/c/{short}",
    }
    payload.update(overrides)
    return payload


def handoff(text="Done: built\nVerified-how: tests\nRemaining: none\nSurprises: none", date="2026-07-08T10:00:00Z"):
    return {"date": date, "data": {"text": text}}


class FakeTrello:
    def __init__(self, trigger_cards=None, cards=None, actions=None):
        self.trigger_cards = trigger_cards or []
        self.cards = cards or {item["id"]: item for item in self.trigger_cards}
        self.actions = actions or {}
        self.comments = []
        self.list_calls = []
        self.card_calls = []

    def list_cards(self, list_id):
        self.list_calls.append(list_id)
        return list(self.trigger_cards)

    def get_card(self, card_id):
        self.card_calls.append(card_id)
        return self.cards[card_id]

    def list_comment_actions(self, card_id):
        return list(self.actions.get(card_id, []))

    def add_comment(self, card_id, text):
        self.comments.append((card_id, text))
        return {"id": f"comment-{len(self.comments)}"}


class FakePortal:
    def __init__(self):
        self.reports = []
        self.messages = []

    def stream_url(self, slug):
        return f"http://portal.local/s/{slug}"

    def post_report(self, slug, title, text, *, kind, card_url=None):
        self.reports.append(
            {
                "slug": slug,
                "title": title,
                "text": text,
                "kind": kind,
                "card_url": card_url,
            }
        )
        return {"post": {"id": f"p_{len(self.reports)}"}}

    def post_human_message(self, slug, text):
        self.messages.append({"slug": slug, "text": text})
        return {"id": f"m_{len(self.messages)}"}


def make_watcher(
    repo,
    trello,
    portal,
    *,
    runner=None,
    env=None,
    max_stage="aesthetics_reviewed",
    redaction_secrets=None,
):
    watch_config = trello_watch.load_watch_config(Path(repo), max_stage=max_stage)
    return trello_watch.Watcher(
        watch_config,
        trello,
        portal,
        runner=runner or (lambda _repo, _short, _env: trello_watch.RunResult(0, "ok")),
        env=env or {"TRELLO_API_KEY": "key", "TRELLO_TOKEN": "token", "PATH": "/bin"},
        clock=lambda: 1.0,
        redaction_secrets=redaction_secrets,
    )


def test_load_watch_config_defaults_and_context_state_file(data_dir, tmp_path):
    repo = write_repo(tmp_path)

    cfg = trello_watch.load_watch_config(repo)
    raw = trello_watch.load_watch_config(repo, trigger_list="raw-list-id")

    assert cfg.trigger_list_id == TODO_ID
    assert cfg.trigger_stage == "todo"
    assert cfg.max_stage == "aesthetics_reviewed"
    assert cfg.state_path.parent == data_dir[0] / "trello-watch"
    assert raw.trigger_list_id == "raw-list-id"
    assert raw.trigger_stage is None
    assert raw.state_path != cfg.state_path
    assert trello_watch.stream_slug_for_card("08KM8i8Q") == "trello-08km8i8q"


def test_load_watch_config_rejects_invalid_max_stage(tmp_path):
    repo = write_repo(tmp_path)

    with pytest.raises(trello_watch.WatchError, match="unknown"):
        trello_watch.load_watch_config(repo, max_stage="merged")


def test_state_store_survives_restart_and_rejects_corrupt_json(tmp_path):
    path = tmp_path / "state.json"
    store = trello_watch.StateStore(path)
    state = {"version": 1, "cards": {"card-1": {"status": "tracking"}}}

    store.save(state)

    assert trello_watch.StateStore(path).load() == state
    path.write_text("{not-json")
    with pytest.raises(trello_watch.WatchError, match="corrupt"):
        trello_watch.StateStore(path).load()
    assert path.read_text() == "{not-json"


def test_pickup_posts_report_once_and_reuses_state_after_restart(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    first_card = card(name="Build <portal>")
    trello = FakeTrello(
        trigger_cards=[first_card],
        actions={"card-1": [handoff()]},
    )
    portal = FakePortal()
    runner_calls = []

    def runner(repo_arg, short, env):
        runner_calls.append((repo_arg, short, env))
        return trello_watch.RunResult(0, "stage complete")

    make_watcher(repo, trello, portal, runner=runner).poll_once()
    make_watcher(repo, trello, portal, runner=runner).poll_once()

    pickups = [report for report in portal.reports if report["kind"] == "pickup"]
    assert len(pickups) == 1
    assert pickups[0]["slug"] == "trello-08km8i8q"
    assert pickups[0]["title"] == "Picked up Build <portal>"
    assert [call[1] for call in runner_calls] == ["08KM8i8Q", "08KM8i8Q"]


def test_one_stage_per_pass_for_each_tracked_card(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    cards = [
        card("card-1", "AAAA1111", "First"),
        card("card-2", "BBBB2222", "Second"),
    ]
    trello = FakeTrello(trigger_cards=cards, actions={"card-1": [handoff()], "card-2": [handoff()]})
    portal = FakePortal()
    runner_calls = []

    def runner(repo_arg, short, env):
        runner_calls.append(short)
        return trello_watch.RunResult(0, "ok")

    make_watcher(repo, trello, portal, runner=runner).poll_once()

    assert runner_calls == ["AAAA1111", "BBBB2222"]
    assert trello.list_calls == [TODO_ID]


def test_tracked_card_advances_after_leaving_trigger_list(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    tracked = card("card-1", "AAAA1111", "Tracked", list_id=TODO_ID)
    trello = FakeTrello(trigger_cards=[], cards={"card-1": tracked}, actions={"card-1": [handoff()]})
    portal = FakePortal()
    runner_calls = []
    watcher = make_watcher(repo, trello, portal, runner=lambda _repo, short, _env: runner_calls.append(short) or trello_watch.RunResult(0, "ok"))
    state = watcher.state_store.load()
    state["cards"] = {
        "card-1": {
            "card_id": "card-1",
            "short_link": "AAAA1111",
            "title": "Tracked",
            "stream_slug": "trello-aaaa1111",
            "status": "tracking",
            "pickup_reported": True,
            "human_notified": False,
        }
    }
    watcher.state_store.save(state)

    watcher.poll_once()

    assert runner_calls == ["AAAA1111"]
    assert trello.card_calls == ["card-1"]


@pytest.mark.parametrize(
    ("list_id", "expected"),
    [
        (MAX_ID, "max-stage is aesthetics_reviewed"),
        (BLOCKED_ID, "blocked_on_batu"),
    ],
)
def test_stop_conditions_post_to_human_without_runner(data_dir, tmp_path, list_id, expected):
    repo = write_repo(tmp_path)
    stopped = card(list_id=list_id)
    trello = FakeTrello(trigger_cards=[stopped], actions={"card-1": [handoff()]})
    portal = FakePortal()
    runner_calls = []

    make_watcher(
        repo,
        trello,
        portal,
        runner=lambda _repo, short, _env: runner_calls.append(short) or trello_watch.RunResult(0, "ok"),
    ).poll_once()

    assert runner_calls == []
    assert len(portal.messages) == 1
    assert expected in portal.messages[0]["text"]


def test_past_max_stage_posts_to_human_without_runner(data_dir, tmp_path):
    repo = write_repo(
        tmp_path,
        lists={
            "todo": TODO_ID,
            "worked": WORKED_ID,
            "aesthetics_reviewed": MAX_ID,
            "evidence": "list-evidence",
            "blocked_on_batu": BLOCKED_ID,
        },
    )
    trello = FakeTrello(trigger_cards=[card(list_id="list-evidence")])
    portal = FakePortal()
    runner_calls = []

    make_watcher(
        repo,
        trello,
        portal,
        runner=lambda _repo, short, _env: runner_calls.append(short) or trello_watch.RunResult(0, "ok"),
    ).poll_once()

    assert runner_calls == []
    assert len(portal.messages) == 1
    assert "reached evidence" in portal.messages[0]["text"]
    assert "max-stage is aesthetics_reviewed" in portal.messages[0]["text"]


def test_stopped_state_retries_missing_human_message(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    trello = FakeTrello(trigger_cards=[card(list_id=MAX_ID)])

    class FlakyPortal(FakePortal):
        def __init__(self):
            super().__init__()
            self.failures_left = 1

        def post_human_message(self, slug, text):
            if self.failures_left:
                self.failures_left -= 1
                raise gallery_client.GalleryClientError(503, "portal unavailable")
            return super().post_human_message(slug, text)

    portal = FlakyPortal()
    runner_calls = []
    watcher = make_watcher(
        repo,
        trello,
        portal,
        runner=lambda _repo, short, _env: runner_calls.append(short) or trello_watch.RunResult(0, "ok"),
    )

    watcher.poll_once()
    saved_after_transient = watcher.state_store.load()["cards"]["card-1"]
    assert saved_after_transient["status"] == "stopped"
    assert saved_after_transient["human_notified"] is False
    assert "portal unavailable" in saved_after_transient["last_transient_error"]

    watcher.poll_once()
    saved_after_retry = watcher.state_store.load()["cards"]["card-1"]
    assert runner_calls == []
    assert saved_after_retry["human_notified"] is True
    assert len(portal.messages) == 1


def test_error_path_marks_and_skips_without_duplicate_messages(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    trello = FakeTrello(trigger_cards=[card()])
    portal = FakePortal()
    runner_calls = []
    env = {
        "TRELLO_API_KEY": "trello-key",
        "TRELLO_TOKEN": "trello-token",
        "GALLERY_TOKEN": "gallery-token",
        "PATH": "/bin",
    }

    def runner(_repo, short, _env):
        runner_calls.append(short)
        return trello_watch.RunResult(
            7,
            "failed https://x.test/?token=gallery-token trello-key trello-token Authorization: Bearer gallery-token",
        )

    watcher = make_watcher(repo, trello, portal, runner=runner, env=env)
    watcher.poll_once()
    watcher.poll_once()
    state = watcher.state_store.load()

    assert runner_calls == ["08KM8i8Q"]
    assert state["cards"]["card-1"]["status"] == "errored"
    tail = state["cards"]["card-1"]["last_run"]["tail"]
    assert "trello-key" not in tail
    assert "trello-token" not in tail
    assert "gallery-token" not in tail
    assert "token=[redacted]" in tail
    assert len([report for report in portal.reports if report["kind"] == "failure"]) == 1
    assert len(portal.messages) == 1


def test_trello_title_and_card_url_tokens_are_redacted_in_reports(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    secret = "gallery-title-token"
    env = {
        "TRELLO_API_KEY": "key",
        "TRELLO_TOKEN": "token",
        "GALLERY_TOKEN": secret,
        "PATH": "/bin",
    }
    trello = FakeTrello(
        trigger_cards=[
            card(
                name=f"Build {secret} https://x.test/?token={secret}",
                url=f"https://trello.example/card?token={secret}",
            )
        ]
    )
    portal = FakePortal()

    def runner(_repo, _short, _env):
        return trello_watch.RunResult(7, "boom")

    make_watcher(repo, trello, portal, runner=runner, env=env).poll_once()

    for report in portal.reports:
        assert secret not in report["title"]
        assert secret not in report["text"]
        assert secret not in (report["card_url"] or "")
    assert "[redacted]" in portal.reports[0]["title"]
    assert "=[redacted]" in portal.reports[0]["text"]


def test_successful_run_transient_handoff_fetch_retries_without_rerun(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    trello = FakeTrello(trigger_cards=[card()])
    portal = FakePortal()
    runner_calls = []
    action_calls = 0

    def runner(_repo, short, _env):
        runner_calls.append(short)
        return trello_watch.RunResult(0, "ok")

    def list_comment_actions(card_id):
        nonlocal action_calls
        action_calls += 1
        if action_calls == 1:
            raise trello_watch.TrelloAPIError(429, "rate limit")
        return [handoff()]

    trello.list_comment_actions = list_comment_actions
    watcher = make_watcher(repo, trello, portal, runner=runner)

    watcher.poll_once()
    saved_after_transient = watcher.state_store.load()["cards"]["card-1"]
    assert runner_calls == ["08KM8i8Q"]
    assert saved_after_transient["status"] == "pending_report"
    assert saved_after_transient["last_run"]["handoff_reported"] is False

    watcher.poll_once()
    saved_after_retry = watcher.state_store.load()["cards"]["card-1"]
    assert runner_calls == ["08KM8i8Q"]
    assert saved_after_retry["status"] == "tracking"
    assert saved_after_retry["last_run"]["handoff_reported"] is True
    assert saved_after_retry["last_run"]["trello_commented"] is True
    assert [report["kind"] for report in portal.reports] == ["pickup", "handoff"]
    assert len(trello.comments) == 1


def test_successful_run_transient_trello_comment_retries_without_rerun(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    trello = FakeTrello(trigger_cards=[card()], actions={"card-1": [handoff()]})
    portal = FakePortal()
    runner_calls = []
    comment_calls = 0

    def runner(_repo, short, _env):
        runner_calls.append(short)
        return trello_watch.RunResult(0, "ok")

    def add_comment(card_id, text):
        nonlocal comment_calls
        comment_calls += 1
        if comment_calls == 1:
            raise trello_watch.TrelloAPIError(429, "rate limit")
        return FakeTrello.add_comment(trello, card_id, text)

    trello.add_comment = add_comment
    watcher = make_watcher(repo, trello, portal, runner=runner)

    summary = watcher.poll_once()
    saved_after_transient = watcher.state_store.load()["cards"]["card-1"]
    assert summary["advanced"] == 1
    assert summary["cards"] == [
        {
            "card_id": "card-1",
            "short_link": "08KM8i8Q",
            "stream_slug": "trello-08km8i8q",
            "status": "pending_report",
            "action": "advanced",
            "retryable": True,
            "reason": "Trello HTTP 429: rate limit",
        }
    ]
    assert runner_calls == ["08KM8i8Q"]
    assert saved_after_transient["status"] == "pending_report"
    assert saved_after_transient["last_run"]["handoff_reported"] is True
    assert saved_after_transient["last_run"]["trello_commented"] is False

    watcher.poll_once()
    saved_after_retry = watcher.state_store.load()["cards"]["card-1"]
    assert runner_calls == ["08KM8i8Q"]
    assert saved_after_retry["status"] == "tracking"
    assert saved_after_retry["last_run"]["trello_commented"] is True
    assert [report["kind"] for report in portal.reports] == ["pickup", "handoff"]
    assert len(trello.comments) == 1


def test_successful_run_transient_portal_report_retries_without_rerun(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    trello = FakeTrello(trigger_cards=[card()], actions={"card-1": [handoff()]})

    class FlakyPortal(FakePortal):
        def __init__(self):
            super().__init__()
            self.failures_left = 1

        def post_report(self, *args, **kwargs):
            if kwargs.get("kind") == "handoff" and self.failures_left:
                self.failures_left -= 1
                raise gallery_client.GalleryClientError(503, "portal unavailable")
            return super().post_report(*args, **kwargs)

    portal = FlakyPortal()
    runner_calls = []

    def runner(_repo, short, _env):
        runner_calls.append(short)
        return trello_watch.RunResult(0, "ok")

    watcher = make_watcher(repo, trello, portal, runner=runner)

    watcher.poll_once()
    saved_after_transient = watcher.state_store.load()["cards"]["card-1"]
    assert runner_calls == ["08KM8i8Q"]
    assert saved_after_transient["status"] == "pending_report"
    assert saved_after_transient["last_run"]["handoff_reported"] is False
    assert "portal unavailable" in saved_after_transient["last_transient_error"]

    watcher.poll_once()
    saved_after_retry = watcher.state_store.load()["cards"]["card-1"]
    assert runner_calls == ["08KM8i8Q"]
    assert saved_after_retry["status"] == "tracking"
    assert saved_after_retry["last_run"]["handoff_reported"] is True
    assert [report["kind"] for report in portal.reports] == ["pickup", "handoff"]
    assert len(trello.comments) == 1


def test_errored_state_retries_missing_failure_report_without_rerun(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    trello = FakeTrello(trigger_cards=[card()])

    class FlakyPortal(FakePortal):
        def __init__(self):
            super().__init__()
            self.failures_left = 1

        def post_report(self, *args, **kwargs):
            if kwargs.get("kind") == "failure" and self.failures_left:
                self.failures_left -= 1
                raise RuntimeError("portal unavailable")
            return super().post_report(*args, **kwargs)

    portal = FlakyPortal()
    runner_calls = []

    def runner(_repo, short, _env):
        runner_calls.append(short)
        return trello_watch.RunResult(7, "boom")

    watcher = make_watcher(repo, trello, portal, runner=runner)

    with pytest.raises(RuntimeError, match="portal unavailable"):
        watcher.poll_once()

    saved_after_failure = watcher.state_store.load()["cards"]["card-1"]
    assert saved_after_failure["status"] == "errored"
    assert not saved_after_failure["last_run"].get("failure_reported")

    watcher.poll_once()

    saved_after_retry = watcher.state_store.load()["cards"]["card-1"]
    assert runner_calls == ["08KM8i8Q"]
    assert saved_after_retry["last_run"]["failure_reported"] is True
    assert len([report for report in portal.reports if report["kind"] == "failure"]) == 1
    assert len(portal.messages) == 1


def test_config_backed_portal_token_is_redacted_when_env_absent(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    trello = FakeTrello(trigger_cards=[card()])
    portal = FakePortal()
    portal_token = data_dir[1]["token"]
    env = {"TRELLO_API_KEY": "key", "TRELLO_TOKEN": "token", "PATH": "/bin"}

    def runner(_repo, _short, _env):
        return trello_watch.RunResult(7, f"failed with portal token {portal_token}")

    watcher = make_watcher(
        repo,
        trello,
        portal,
        runner=runner,
        env=env,
        redaction_secrets=trello_watch.redaction_secrets(env, portal_token=portal_token),
    )

    watcher.poll_once()
    tail = watcher.state_store.load()["cards"]["card-1"]["last_run"]["tail"]

    assert portal_token not in tail
    assert portal_token not in portal.reports[-1]["text"]
    assert "[redacted]" in tail


def test_output_is_redacted_before_tail_boundary(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    trello = FakeTrello(trigger_cards=[card()])
    portal = FakePortal()
    secret = "split-boundary-gallery-token"
    env = {
        "TRELLO_API_KEY": "key",
        "TRELLO_TOKEN": "token",
        "GALLERY_TOKEN": secret,
        "PATH": "/bin",
    }
    output = ("x" * 20) + secret + ("z" * 7990)

    def runner(_repo, _short, _env):
        return trello_watch.RunResult(7, output)

    watcher = make_watcher(repo, trello, portal, runner=runner, env=env)

    watcher.poll_once()
    tail = watcher.state_store.load()["cards"]["card-1"]["last_run"]["tail"]

    assert secret not in tail
    assert secret[-12:] not in tail
    assert "[redacted]" in tail


def test_run_twf_card_delegates_to_run_subprocess(monkeypatch, tmp_path):
    calls = []

    def fake_run_subprocess(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return trello_watch.RunResult(0, "out")

    monkeypatch.setattr(trello_watch, "_run_subprocess", fake_run_subprocess)

    result = trello_watch.run_twf_card(tmp_path, "08KM8i8Q", {"TRELLO_API_KEY": "k", "TRELLO_TOKEN": "t"})

    assert result == trello_watch.RunResult(0, "out")
    assert calls == [
        (
            ["twf", "run-card", "08KM8i8Q", "--worktree"],
            {
                "cwd": tmp_path,
                "env": {"TRELLO_API_KEY": "k", "TRELLO_TOKEN": "t"},
                "timeout": trello_watch.RUN_TIMEOUT_SECONDS,
                "grace": trello_watch.RUN_GRACE_SECONDS,
            },
        )
    ]


def test_run_twf_card_propagates_timeout_result(monkeypatch, tmp_path):
    def fake_run_subprocess(cmd, **kwargs):
        return trello_watch.RunResult(124, "partial\ntwf run-card timed out after 60s", timed_out=True)

    monkeypatch.setattr(trello_watch, "_run_subprocess", fake_run_subprocess)

    result = trello_watch.run_twf_card(tmp_path, "08KM8i8Q", {"TRELLO_API_KEY": "k", "TRELLO_TOKEN": "t"})

    assert result.returncode == 124
    assert result.timed_out is True
    assert "partial" in result.output
    assert "timed out" in result.output


def test_trello_client_requests_encode_paths_queries_and_forms():
    calls = []
    bodies = iter(
        [
            b'[{"id":"card-1"}]',
            b'{"id":"card-1"}',
            b'[{"id":"action-1"}]',
            b'{"id":"comment-1"}',
        ]
    )

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body

    def opener(req, timeout):
        calls.append((req, timeout))
        return Response(next(bodies))

    client = trello_watch.TrelloClient("api key", "tok/en", opener=opener)

    assert client.list_cards("list/1") == [{"id": "card-1"}]
    assert client.get_card("card/1") == {"id": "card-1"}
    assert client.list_comment_actions("card/1") == [{"id": "action-1"}]
    assert client.add_comment("card/1", "hello world") == {"id": "comment-1"}

    list_req, timeout = calls[0]
    assert timeout == 30
    assert list_req.get_method() == "GET"
    parsed = urllib.parse.urlsplit(list_req.full_url)
    assert parsed.path == "/1/lists/list%2F1/cards"
    query = urllib.parse.parse_qs(parsed.query)
    assert query["key"] == ["api key"]
    assert query["token"] == ["tok/en"]
    assert query["fields"] == ["id,shortLink,name,idList,closed,idBoard,url"]

    add_req, _timeout = calls[3]
    assert add_req.get_method() == "POST"
    assert urllib.parse.urlsplit(add_req.full_url).path == "/1/cards/card%2F1/actions/comments"
    assert urllib.parse.parse_qs(add_req.data.decode("utf-8")) == {"text": ["hello world"]}
    assert add_req.headers["Content-type"] == "application/x-www-form-urlencoded"


def test_trello_client_maps_http_and_network_errors():
    def http_error(_req, timeout):
        raise urllib.error.HTTPError(
            url="https://api.trello.test",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=BytesIO(b'{"message":"bad token"}'),
        )

    client = trello_watch.TrelloClient("key", "token", opener=http_error)
    with pytest.raises(trello_watch.TrelloAPIError) as http_exc:
        client.get_card("card-1")

    assert http_exc.value.status == 403
    assert http_exc.value.message == "bad token"
    assert http_exc.value.transient is False

    def network_error(_req, timeout):
        raise urllib.error.URLError("offline")

    client = trello_watch.TrelloClient("key", "token", opener=network_error)
    with pytest.raises(trello_watch.TrelloAPIError) as network_exc:
        client.get_card("card-1")

    assert network_exc.value.status == 0
    assert network_exc.value.transient is True


def test_pending_report_restart_does_not_rerun_twf(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    trello = FakeTrello(trigger_cards=[], cards={"card-1": card()}, actions={"card-1": [handoff("Done: resumed\nVerified-how: fake\nRemaining: none\nSurprises: none")]})
    portal = FakePortal()
    watcher = make_watcher(
        repo,
        trello,
        portal,
        runner=lambda *_args: pytest.fail("pending report must not rerun twf"),
    )
    state = watcher.state_store.load()
    state["cards"] = {
        "card-1": {
            "card_id": "card-1",
            "short_link": "08KM8i8Q",
            "title": "Build it",
            "stream_slug": "trello-08km8i8q",
            "status": "pending_report",
            "pickup_reported": True,
            "human_notified": False,
            "last_run": {
                "started_at": "1970-01-01T00:00:01Z",
                "finished_at": "1970-01-01T00:00:02Z",
                "returncode": 0,
                "tail": "ok",
                "handoff_reported": False,
                "trello_commented": False,
            },
        }
    }
    watcher.state_store.save(state)

    watcher.poll_once()
    saved = watcher.state_store.load()["cards"]["card-1"]

    assert saved["status"] == "tracking"
    assert saved["last_run"]["handoff_reported"] is True
    assert saved["last_run"]["trello_commented"] is True
    assert [report["kind"] for report in portal.reports] == ["handoff"]
    assert trello.comments[0][0] == "card-1"
    assert "?token=" not in trello.comments[0][1]


def test_stale_running_state_becomes_errored_without_rerun(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    trello = FakeTrello(trigger_cards=[], cards={"card-1": card()})
    portal = FakePortal()
    watcher = make_watcher(repo, trello, portal, runner=lambda *_args: pytest.fail("stale running must not rerun"))
    state = watcher.state_store.load()
    state["cards"] = {
        "card-1": {
            "card_id": "card-1",
            "short_link": "08KM8i8Q",
            "title": "Build it",
            "stream_slug": "trello-08km8i8q",
            "status": "running",
            "pickup_reported": True,
            "human_notified": False,
        }
    }
    watcher.state_store.save(state)

    watcher.poll_once()

    saved = watcher.state_store.load()["cards"]["card-1"]
    assert saved["status"] == "errored"
    assert len(portal.messages) == 1


def test_transient_trigger_scan_failure_does_not_mutate_state(data_dir, tmp_path):
    repo = write_repo(tmp_path)

    class TransientTrello(FakeTrello):
        def list_cards(self, list_id):
            raise trello_watch.TrelloAPIError(429, "rate limit")

    watcher = make_watcher(repo, TransientTrello(), FakePortal())

    summary = watcher.poll_once()

    assert "rate limit" in summary["transient_error"]
    assert not watcher.state_store.path.exists()


def test_build_runner_env_allowlists_runtime_and_required_trello_only():
    env = trello_watch.build_runner_env(
        {
            "PATH": "/bin",
            "HOME": "/home/me",
            "TRELLO_API_KEY": "key",
            "TRELLO_TOKEN": "token",
            "TRELLO_EXTRA": "nope",
            "GALLERY_TOKEN": "nope",
            "GALLERY_TELEGRAM_BOT_TOKEN": "nope",
            "SECRET_THING": "nope",
        }
    )

    assert env == {
        "HOME": "/home/me",
        "PATH": "/bin",
        "TRELLO_API_KEY": "key",
        "TRELLO_TOKEN": "token",
    }


def test_portal_reporter_writes_escaped_html_file(data_dir, monkeypatch):
    captured = {}

    def fake_create_stream_post(base_url, token, slug, type, title, author, body=None, files=None):
        captured.update(
            {
                "base_url": base_url,
                "token": token,
                "slug": slug,
                "type": type,
                "title": title,
                "author": author,
                "body": body,
                "files": files,
            }
        )
        return {"post": {"id": "p_1"}}

    monkeypatch.setattr(trello_watch.client, "create_stream_post", fake_create_stream_post)
    reporter = trello_watch.PortalReporter("http://portal.local?token=must-not-appear", "portal-token")

    reporter.post_report(
        "trello-08km8i8q",
        "Picked <script>",
        "body </pre><img src=x onerror=alert(1)>",
        kind="pickup",
        card_url="https://trello.com/c/08KM8i8Q",
    )

    assert reporter.stream_url("trello-08km8i8q") == "http://portal.local/s/trello-08km8i8q"
    assert captured["base_url"] == "http://portal.local"
    assert captured["type"] == "report"
    assert captured["files"] and captured["files"][0].is_file()
    html = captured["files"][0].read_text()
    assert "<script>" not in html
    assert "</pre><img" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;/pre&gt;&lt;img" in html


def test_cli_trello_watch_help_lists_required_flags(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["portal", "trello-watch", "--help"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    for text in ["--repo", "--list", "--interval", "--once", "--max-stage"]:
        assert text in out
    for text in ["foreground polling", "JSON summary line", "retryable one-shot failure 75", "transient_error"]:
        assert text in out


def test_cli_trello_watch_once_runs_single_pass_without_sleep(monkeypatch, capsys):
    class FakeWatcher:
        def __init__(self):
            self.calls = 0

        def poll_once(self):
            self.calls += 1
            return {"picked_up": self.calls}

    fake = FakeWatcher()
    monkeypatch.setattr(cli.trello_watch, "build_watcher", lambda repo, trigger_list=None, max_stage="aesthetics_reviewed": fake)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: pytest.fail("--once must not sleep"))
    monkeypatch.setattr(
        "sys.argv",
        ["portal", "trello-watch", "--repo", "/tmp/repo", "--list", "todo", "--interval", "5", "--once"],
    )

    cli.main()

    assert fake.calls == 1
    assert json.loads(capsys.readouterr().out) == {"picked_up": 1}


def test_cli_trello_watch_once_transient_exits_retryable(monkeypatch, capsys):
    class FakeWatcher:
        def poll_once(self):
            return {"transient_error": "Trello HTTP 429: rate limit"}

    monkeypatch.setattr(cli.trello_watch, "build_watcher", lambda *args, **kwargs: FakeWatcher())
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: pytest.fail("--once must not sleep"))
    monkeypatch.setattr("sys.argv", ["portal", "trello-watch", "--repo", "/tmp/repo", "--once"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 75
    assert json.loads(capsys.readouterr().out) == {"transient_error": "Trello HTTP 429: rate limit"}


def test_cli_trello_watch_once_card_retryable_exits_retryable(monkeypatch, capsys):
    summary = {"cards": [{"short_link": "08KM8i8Q", "status": "pending_report", "retryable": True}]}

    class FakeWatcher:
        def poll_once(self):
            return summary

    monkeypatch.setattr(cli.trello_watch, "build_watcher", lambda *args, **kwargs: FakeWatcher())
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: pytest.fail("--once must not sleep"))
    monkeypatch.setattr("sys.argv", ["portal", "trello-watch", "--repo", "/tmp/repo", "--once"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 75
    assert json.loads(capsys.readouterr().out) == summary


def test_cli_trello_watch_errors_exit_1(monkeypatch, capsys):
    def fail(*_args, **_kwargs):
        raise trello_watch.WatchError("bad config")

    monkeypatch.setattr(cli.trello_watch, "build_watcher", fail)
    monkeypatch.setattr("sys.argv", ["portal", "trello-watch", "--repo", "/tmp/repo", "--once"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "error: bad config" in capsys.readouterr().err
