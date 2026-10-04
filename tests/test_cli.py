from recall.cli import main


def run(capsys, *argv):
    try:
        main(list(argv))
    except SystemExit as e:
        code = e.code
    else:
        code = 0
    return code, capsys.readouterr().out


def test_cli_roundtrip(tmp_path, capsys):
    db = str(tmp_path / "m.json")
    assert run(capsys, "--db", db, "add", "I live in Toronto")[0] == 0
    code, out = run(capsys, "--db", db, "ask", "where do I live")
    assert code == 0 and "Toronto" in out
    run(capsys, "--db", db, "add", "I moved to Berlin")
    _, out = run(capsys, "--db", db, "list")
    assert "Berlin" in out and "Toronto" not in out
    code, out = run(capsys, "--db", db, "stats")
    assert "superseded" in out


def test_demo_runs(capsys):
    code, out = run(capsys, "demo")
    assert code == 0 and "SUPERSEDES" in out and "DISPUTED" in out
