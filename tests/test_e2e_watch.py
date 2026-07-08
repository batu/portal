import json
from pathlib import Path

from gallery import trello_watch


BOARD_ID = "board-1"
TODO_ID = "list-todo"
WORKED_ID = "list-worked"
MAX_ID = "list-max"
BLOCKED_ID = "list-blocked"


def write_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    config = {
        "trello": {
            "board_id": BOARD_ID,
            "board_name": "phase23 board",
            "lists": {
                "todo": TODO_ID,
                "worked": WORKED_ID,
                "aesthetics_reviewed": MAX_ID,
                "blocked_on_batu": BLOCKED_ID,
            },
        }
    }
    (repo / "agents" / "config.json").write_text(json.dumps(config))
    return repo


def card(card_id="card-1", short="hVtTtwRa", name="Phase 2/3 proof", list_id=TODO_ID):
    return {
        "id": card_id,
        "shortLink": short,
        "name": name,
        "idList": list_id,
        "idBoard": BOARD_ID,
        "closed": False,
        "url": f"https://trello.com/c/{short}",
    }


def handoff():
    return {
        "date": "2026-07-08T10:00:00Z",
        "data": {
            "text": "\n".join(
                [
                    "Done: implemented one stage",
                    "Verified-how: focused fake watcher run",
                    "Remaining: next twf stage",
                    "Surprises: none",
                ]
            )
        },
    }


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


def make_watcher(repo, trello, portal, *, runner, env):
    watch_config = trello_watch.load_watch_config(Path(repo), max_stage="aesthetics_reviewed")
    return trello_watch.Watcher(
        watch_config,
        trello,
        portal,
        runner=runner,
        env=env,
        clock=lambda: 1.0,
        redaction_secrets=["portal-secret"],
    )


def assert_no_secret_text(text):
    forbidden = [
        "trello-key",
        "trello-token",
        "portal-secret",
        "Authorization: Bearer",
        "?token=",
        "&token=",
    ]
    for value in forbidden:
        assert value not in text


def test_trello_watch_pickup_one_stage_max_stage_stop_and_idempotence(data_dir, tmp_path):
    repo = write_repo(tmp_path)
    watched_card = card()
    trello = FakeTrello(trigger_cards=[watched_card], actions={"card-1": [handoff()]})
    portal = FakePortal()
    runner_calls = []
    env = {
        "TRELLO_API_KEY": "trello-key",
        "TRELLO_TOKEN": "trello-token",
        "GALLERY_TOKEN": "portal-secret",
        "PATH": "/bin",
    }

    def runner(repo_arg, short, run_env):
        runner_calls.append(
            {
                "repo": str(repo_arg),
                "short": short,
                "env_keys": sorted(run_env),
            }
        )
        return trello_watch.RunResult(0, "fake twf run-card hVtTtwRa --worktree completed")

    watcher = make_watcher(repo, trello, portal, runner=runner, env=env)

    first = watcher.poll_once()

    assert first["picked_up"] == 1
    assert first["advanced"] == 1
    assert first["stopped"] == 0
    assert runner_calls == [
        {
            "repo": str(repo.resolve()),
            "short": "hVtTtwRa",
            "env_keys": ["PATH", "TRELLO_API_KEY", "TRELLO_TOKEN"],
        }
    ]
    assert [report["kind"] for report in portal.reports] == ["pickup", "handoff"]
    assert portal.reports[0]["slug"] == "trello-hvtttwra"
    assert portal.reports[0]["title"] == "Picked up Phase 2/3 proof"
    assert "Done: implemented one stage" in portal.reports[1]["text"]
    assert trello.comments == [
        (
            "card-1",
            "Portal report: http://portal.local/s/trello-hvtttwra\n"
            "Status: completed one twf stage for hVtTtwRa.",
        )
    ]
    assert portal.messages == []

    watched_card["idList"] = MAX_ID
    trello.trigger_cards = []
    counts_after_first = (len(portal.reports), len(portal.messages), len(trello.comments), len(runner_calls))

    second = watcher.poll_once()

    assert second["picked_up"] == 0
    assert second["advanced"] == 0
    assert second["stopped"] == 1
    assert (len(portal.reports), len(trello.comments), len(runner_calls)) == (
        counts_after_first[0],
        counts_after_first[2],
        counts_after_first[3],
    )
    assert len(portal.messages) == counts_after_first[1] + 1
    assert portal.messages[0]["slug"] == "trello-hvtttwra"
    assert "reached aesthetics_reviewed" in portal.messages[0]["text"]
    assert "max-stage is aesthetics_reviewed" in portal.messages[0]["text"]

    counts_after_second = (len(portal.reports), len(portal.messages), len(trello.comments), len(runner_calls))
    third = watcher.poll_once()

    assert third["picked_up"] == 0
    assert third["advanced"] == 0
    assert third["stopped"] == 0
    assert third["skipped"] == 1
    assert (len(portal.reports), len(portal.messages), len(trello.comments), len(runner_calls)) == counts_after_second

    transcript = json.dumps(
        {
            "first_summary": first,
            "second_summary": second,
            "third_summary": third,
            "runner_calls": runner_calls,
            "portal_reports": portal.reports,
            "portal_messages": portal.messages,
            "trello_comments": trello.comments,
            "fake_boundaries": {
                "network": "fake Trello and fake Portal only",
                "subprocess": "fake runner only",
            },
        },
        sort_keys=True,
    )
    assert_no_secret_text(transcript)
