"""`recall install` / `recall uninstall` for every agent, in a throwaway home folder."""
import json
import os

import pytest

from recall.integrations import AGENTS, find, install, make_ctx, status, uninstall

LAUNCHER = ["/opt/recall/bin/recall"]


def ctx_for(tmp_path):
    return make_ctx(home=str(tmp_path / "home"), launcher=LAUNCHER, env={})


def tree(root):
    out = set()
    for d, _, files in os.walk(root):
        for f in files:
            out.add(os.path.relpath(os.path.join(d, f), root).replace("\\", "/"))
    return out


@pytest.mark.parametrize("agent", AGENTS, ids=[a.id for a in AGENTS])
def test_install_then_uninstall_leaves_no_trace(agent, tmp_path, home):
    ctx = ctx_for(tmp_path)
    os.makedirs(ctx.home)
    assert status(agent, ctx) == "not installed"
    lines = install(agent, ctx)
    assert not [l for l in lines if l.status == "x"], lines
    assert status(agent, ctx) == "installed"
    for path in tree(ctx.home):
        full = os.path.join(ctx.home, path)
        if path.endswith(".json"):
            json.load(open(full, encoding="utf-8"))           # every JSON we write is valid
        text = open(full, encoding="utf-8").read()
        assert "/opt/recall/bin/recall" in text or path.endswith((".md", ".recall-managed", "plugin.yaml")) \
            or "recall" in text
    install(agent, ctx)                                         # idempotent
    assert status(agent, ctx) == "installed"
    uninstall(agent, ctx)
    assert status(agent, ctx) == "not installed"
    assert tree(ctx.home) == set(), f"left behind: {tree(ctx.home)}"


def test_existing_configs_are_preserved(tmp_path, home):
    ctx = ctx_for(tmp_path)
    cursor = os.path.join(ctx.home, ".cursor")
    os.makedirs(cursor)
    mine = {"mcpServers": {"github": {"command": "gh-mcp"}}}
    with open(os.path.join(cursor, "mcp.json"), "w") as f:
        json.dump(mine, f)
    hooks = {"version": 1, "hooks": {"stop": [{"command": "./my-stop.sh"}]}}
    with open(os.path.join(cursor, "hooks.json"), "w") as f:
        json.dump(hooks, f)
    codex = os.path.join(ctx.home, ".codex")
    os.makedirs(codex)
    with open(os.path.join(codex, "config.toml"), "w") as f:
        f.write('model = "gpt-5"\n')

    install(find("cursor"), ctx)
    install(find("codex"), ctx)
    merged = json.load(open(os.path.join(cursor, "mcp.json")))
    assert set(merged["mcpServers"]) == {"github", "recall"}
    hk = json.load(open(os.path.join(cursor, "hooks.json")))
    assert len(hk["hooks"]["stop"]) == 2 and "sessionStart" in hk["hooks"]
    toml = open(os.path.join(codex, "config.toml")).read()
    assert toml.startswith('model = "gpt-5"') and "[mcp_servers.recall]" in toml

    uninstall(find("cursor"), ctx)
    uninstall(find("codex"), ctx)
    assert json.load(open(os.path.join(cursor, "mcp.json"))) == mine
    assert json.load(open(os.path.join(cursor, "hooks.json"))) == hooks
    assert open(os.path.join(codex, "config.toml")).read() == 'model = "gpt-5"\n'


def test_files_with_comments_are_not_rewritten(tmp_path, home):
    ctx = ctx_for(tmp_path)
    path = os.path.join(ctx.home, ".gemini", "settings.json")
    os.makedirs(os.path.dirname(path))
    original = '{\n  // my settings\n  "theme": "dark"\n}\n'
    open(path, "w").write(original)
    lines = install(find("gemini"), ctx)
    assert any(l.status == "!" and "comments" in l.text for l in lines)
    assert open(path).read() == original


def test_toml_conflicts_are_reported(tmp_path, home):
    ctx = ctx_for(tmp_path)
    path = os.path.join(ctx.home, ".grok", "config.toml")
    os.makedirs(os.path.dirname(path))
    open(path, "w").write("[mcp_servers.recall]\ncommand = 'something-else'\n")
    lines = install(find("grok"), ctx)
    assert any(l.status == "!" and "already defines" in l.text for l in lines)


def test_aliases_and_dry_run(tmp_path, home):
    assert find("claude").id == "claude-code" and find("Grok Build").id == "grok"
    ctx = ctx_for(tmp_path)
    install(find("codex"), ctx, dry=True)
    assert not os.path.exists(ctx.home)


REPO = os.path.join(os.path.dirname(__file__), "..")


def test_committed_plugin_files_are_up_to_date():
    """The manifests at the repo root are generated: run `recall export-repo` after changes."""
    from recall.integrations.repo import read_slug, repo_files
    files = repo_files(read_slug(os.path.join(REPO, "pyproject.toml")))
    for rel, fresh in files.items():
        path = os.path.join(REPO, *rel.split("/"))
        assert os.path.exists(path), f"{rel} is missing: run `recall export-repo`"
        assert open(path, encoding="utf-8").read() == fresh, f"{rel} is stale: run `recall export-repo`"


def test_manifests_agree_and_point_at_real_files():
    from recall import __version__
    from recall.integrations.repo import repo_files
    files = repo_files()
    for rel, text in files.items():
        if rel.endswith(".json"):
            data = json.loads(text)
            if isinstance(data.get("version"), str):         # (hooks files carry a schema version 1)
                assert data["version"] == __version__, rel
            for key in ("hooks", "skills", "commands", "mcpServers"):
                ref = data.get(key)
                if isinstance(ref, str):
                    target = (ref[2:] if ref.startswith("./") else ref).rstrip("/")
                    assert any(f == target or f.startswith(target + "/") for f in files), (rel, key, ref)
    market = json.loads(files[".claude-plugin/marketplace.json"])
    assert market["plugins"][0]["source"] == "./"
    assert "YOUR-GITHUB-USER/recall.git" in files[".agents/plugins/marketplace.json"]
    hooks = json.loads(files["hooks/claude-codex.json"])
    assert hooks["hooks"]["Stop"][0]["hooks"][0]["command"] == "recall hook stop --agent claude-code"


def test_skills_are_valid_agent_skills():
    import re
    from recall.integrations.content import all_skills
    for folder, text in all_skills().items():
        head = text.split("---")[1]
        name = re.search(r"^name: (.+)$", head, re.M).group(1).strip()
        desc = re.search(r"^description: (.+)$", head, re.M).group(1).strip()
        assert name == folder and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
        assert 0 < len(desc) <= 1024
        if desc.startswith('"'):
            json.loads(desc)                      # quoted descriptions are valid YAML/JSON strings


def test_one_version_everywhere():
    import re
    from recall import __version__
    toml = open(os.path.join(REPO, "pyproject.toml"), encoding="utf-8").read()
    assert re.search(r'^version = "([^"]+)"', toml, re.M).group(1) == __version__
