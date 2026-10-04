"""`recall hook`: the same memory behaviour spoken in every agent's dialect."""
import io
import json

from recall.hooks import handle, last_assistant_text, parse_answer, run
from recall.settings import open_memory, save_setting


def ctx_of(out):
    return out.get("hookSpecificOutput", {}).get("additionalContext", "")


def test_session_start_injects_what_is_known(home):
    handle("prompt", "claude-code", {"prompt": "I live in Toronto and I'm vegetarian"})
    out = handle("session-start", "claude-code", {"source": "startup"})
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Lives in Toronto" in ctx_of(out) and "<recall-memory>" in ctx_of(out)


def test_prompts_only_capture_personal_facts(home):
    handle("prompt", "claude-code", {"prompt": "Fix the login bug, my build is failing"})
    handle("prompt", "claude-code", {"prompt": "Where do I live?"})
    handle("prompt", "claude-code", {"prompt": "I work at Shopify"})
    with open_memory() as mem:
        assert [m.content for m in mem.memories()] == ["I work at Shopify"]


def test_has_that_changed_round_trip(home):
    handle("prompt", "claude-code", {"prompt": "I live in Toronto"})
    out = handle("prompt", "claude-code", {"prompt": "I live in Berlin"})
    assert "You said before that you live in Toronto" in ctx_of(out)
    out = handle("prompt", "claude-code", {"prompt": "yes"})
    assert "Recorded the user's answer (yes" in ctx_of(out)
    with open_memory() as mem:
        assert [m.content for m in mem.memories() if m.status.value == "active"] == ["I live in Berlin"]


def test_a_yes_much_later_is_not_taken_as_an_answer(home):
    handle("prompt", "claude-code", {"prompt": "I live in Toronto"})
    handle("prompt", "claude-code", {"prompt": "I live in Berlin"})       # question asked here
    handle("prompt", "claude-code", {"prompt": "Refactor the parser"})    # ignored; asked once more
    handle("prompt", "claude-code", {"prompt": "Run the tests"})          # ignored again; Recall stops asking
    handle("prompt", "claude-code", {"prompt": "yes, do that"})
    with open_memory() as mem:
        assert len(mem.questions()) == 1


def test_auto_yes_setting_skips_the_question(home):
    save_setting("confirm", "auto")
    handle("prompt", "claude-code", {"prompt": "I live in Toronto"})
    out = handle("prompt", "claude-code", {"prompt": "I live in Berlin"})
    assert "Has that changed" not in json.dumps(out)
    with open_memory() as mem:
        assert not mem.questions()


def test_stop_blocks_once_when_the_reply_contradicts_itself(home):
    assert handle("stop", "claude-code", {"last_assistant_message": "The API base URL is api.example.com."}) == {}
    out = handle("stop", "claude-code", {"last_assistant_message": "The API base URL is api.example.org."})
    assert out["decision"] == "block" and "api.example.com" in out["reason"]
    # already continuing because of us: don't block again, raise it next turn instead
    out = handle("stop", "claude-code", {"last_assistant_message": "The API base URL is api.example.net.",
                                         "stop_hook_active": True})
    assert out == {}
    nxt = handle("prompt", "claude-code", {"prompt": "ok thanks"})
    assert "Heads-up from Recall" in ctx_of(nxt)


def test_stop_catches_contradicting_the_user(home):
    handle("prompt", "codex", {"prompt": "I moved to Berlin"})
    out = handle("stop", "codex", {"last_assistant_message": "Since you live in Toronto, use the Toronto office."})
    assert out["decision"] == "block" and "I moved to Berlin" in out["reason"]


def test_gemini_dialect(home):
    handle("prompt", "gemini-cli", {"prompt": "I'm vegetarian"})
    out = handle("prompt", "gemini-cli", {"prompt": "vegetarian"})
    assert out["hookSpecificOutput"]["hookEventName"] == "BeforeAgent"
    handle("stop", "gemini-cli", {"prompt_response": "The cache TTL is 60 seconds."})
    out = handle("stop", "gemini-cli", {"prompt_response": "The cache TTL is 90 seconds."})
    assert out["decision"] == "deny"


def test_cursor_asks_through_a_followup(home):
    assert handle("prompt", "cursor", {"prompt": "I live in Toronto"}) == {"continue": True}
    assert handle("prompt", "cursor", {"prompt": "I live in Berlin"}) == {"continue": True}
    out = handle("stop", "cursor", {"status": "completed", "loop_count": 0})
    assert "You said before that you live in Toronto" in out["followup_message"]
    assert handle("prompt", "cursor", {"prompt": "no"}) == {"continue": True}
    with open_memory() as mem:
        assert [m.content for m in mem.memories() if m.status.value == "active"] == ["I live in Toronto"]


def test_cursor_response_then_stop(home):
    handle("response", "cursor", {"text": "The deploy region is eu-west-1."})
    handle("response", "cursor", {"text": "The deploy region is us-east-1."})
    out = handle("stop", "cursor", {"status": "completed", "loop_count": 0})
    assert "eu-west-1" in out["followup_message"]


def test_copilot_reads_the_transcript(home, tmp_path):
    tr = tmp_path / "t.jsonl"
    lines = [{"type": "user", "message": {"role": "user", "content": "hi"}},
             {"type": "assistant", "message": {"role": "assistant",
                                               "content": [{"type": "text", "text": "The deploy region is eu-west-1."}]}}]
    tr.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    handle("stop", "copilot", {"transcriptPath": str(tr)})
    lines[-1]["message"]["content"][0]["text"] = "The deploy region is us-east-1."
    tr.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    out = handle("stop", "copilot", {"transcriptPath": str(tr)})
    assert out["decision"] == "block"


def test_generic_queue_mode_never_blocks(home):
    handle("stop", "generic", {"response": "The cache TTL is 60 seconds."}, queue_only=True)
    out = handle("stop", "generic", {"response": "The cache TTL is 90 seconds."}, queue_only=True)
    assert out == {}
    out = handle("prompt", "generic", {"prompt": "continue"})
    assert "60 seconds" in out["context"]


def test_run_never_fails(home, capsys):
    assert run("prompt", "claude-code", stdin=io.StringIO("{not json")) == 0
    assert json.loads(capsys.readouterr().out) == {}
    assert run("prompt", "cursor", stdin=io.StringIO("")) == 0
    assert json.loads(capsys.readouterr().out) == {"continue": True}


def test_parse_answer():
    assert parse_answer("yes") is True and parse_answer("Yep, I moved") is True
    assert parse_answer("no") is False and parse_answer("nope, still there") is False
    assert parse_answer("Refactor the parser") is None and parse_answer("") is None


def test_last_assistant_text_shapes(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"messages": [{"role": "user", "content": "x"},
                                          {"role": "assistant", "content": "final answer"}]}), encoding="utf-8")
    assert last_assistant_text(str(p)) == "final answer"
    assert last_assistant_text(str(tmp_path / "missing")) == ""
