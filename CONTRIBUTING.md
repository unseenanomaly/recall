# Contributing to Recall

Thanks for helping! Recall is small on purpose: zero runtime dependencies, one
idea per module.

```bash
git clone https://github.com/unseenanomaly/recall && cd recall
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
python -m recall demo
```

## Ground rules

- **Time is injected.** Never call `time.time()` in library code; use the engine's `clock`.
  This keeps every behaviour testable with `ManualClock`.
- **Every behaviour gets a test**, ideally a short story: *add, advance time, assert*.
- **No runtime dependencies** in the core. Integrations (embeddings, LLM judges, vector DBs)
  belong behind the `relevance_fn`, `Detector`, `Store` and `extractor` extension points.
- Resolutions must stay **explainable**: if you change scoring, `Resolution.reason` and
  `Recall.explain()` must still say *why*.
- **The user is never silently overruled.** A user's statement is either accepted, or turned into
  a "has that changed?" question. Keep it that way.

## Working on agent integrations

- Each agent's install plan lives in `src/recall/integrations/agents.py` as a list of reversible
  actions (`Tree`, `File`, `Files`, `JsonEntry`, `JsonHooks`, `TextBlock`, `Run`, `Note`).
  `recall uninstall` simply undoes the same list, so never write a file outside an action.
- Hook payloads differ per agent; add a `Dialect` in `src/recall/hooks.py` and a test in
  `tests/test_hooks.py` that feeds a realistic payload.
- **The plugin manifests are generated.** The repo root is a plugin for every tool
  (`.claude-plugin/`, `.codex-plugin/`, `.agents/plugins/`, `.github/plugin/`, `.devin-plugin/`,
  `.grok-plugin/`, `gemini-extension.json`, `plugin.yaml` + `__init__.py`, `package.json`, `skills/`,
  `commands/`, `hooks/`, `.mcp.json`, `.opencode/plugins/`, `integrations/`). After changing commands,
  skills, hooks or plugin templates, regenerate them:

  ```bash
  recall export-repo
  ```

  (`tests/test_integrations.py` fails if you forget.) Edit `src/recall/integrations/`, never the
  generated files.
- Try an install without touching your real config:

  ```bash
  RECALL_HOME=/tmp/rh recall install --all --home /tmp/fakehome
  recall uninstall --all --home /tmp/fakehome
  ```

## Releasing

1. **If you fork or rename the repository**, point everything at the new `owner/repo`:

   ```bash
   python scripts/set_repo.py your-name/recall
   ```

   This updates the README, docs and `pyproject.toml`, and regenerates the manifests, including
   the Codex marketplace, which needs the repo's git URL.
2. **Bump the version** in `pyproject.toml` and `src/recall/__init__.py`, run `recall export-repo`
   so every manifest carries it, run `pytest`, then tag the release (`git tag v0.2.1 && git push --tags`).
   Plugin hosts that pin by version (Claude Code, Codex, Gemini) offer the update to users from there.

## Good first issues

- A SQLite `Store`
- An embedding-based `relevance_fn` example
- More claim patterns (other languages welcome)
- Benchmarks for the contradiction detector
- Project-scope installs (`recall install --project`) for agents that support them
