import pytest

from gallery import cli


def test_no_command_prints_help_and_exits(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["gallery"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "usage" in capsys.readouterr().out.lower()


def test_post_requires_title_and_kind(monkeypatch):
    monkeypatch.setattr("sys.argv", ["gallery", "post", "file.png"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2  # argparse error: missing required args


def test_post_rejects_invalid_kind(monkeypatch):
    monkeypatch.setattr("sys.argv", ["gallery", "post", "--title", "t", "--kind", "bogus", "file.png"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2  # argparse choices validation


def test_post_missing_file_exits_1(monkeypatch, tmp_path):
    monkeypatch.setenv("GALLERY_URL", "http://example.invalid")
    monkeypatch.setenv("GALLERY_TOKEN", "x")
    missing = tmp_path / "nope.png"
    monkeypatch.setattr("sys.argv", ["gallery", "post", "--title", "t", "--kind", "pick-one", str(missing)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1


def test_list_parses_flags(monkeypatch):
    parser_args = []
    monkeypatch.setattr(cli, "cmd_list", lambda args: parser_args.append(args))
    monkeypatch.setattr("sys.argv", ["gallery", "list", "--open", "--project", "foo", "--json"])
    cli.main()
    assert len(parser_args) == 1
    assert parser_args[0].open is True
    assert parser_args[0].project == "foo"
    assert parser_args[0].json is True
