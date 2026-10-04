"""The zero-dependency MCP server."""
import io
import json

from recall.mcp import handle, serve


def call(name, **args):
    r = handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": args}})
    text = r["result"]["content"][0]["text"]
    try:
        return json.loads(text), r["result"]["isError"]
    except ValueError:
        return text, r["result"]["isError"]


def test_handshake_and_tool_list(home):
    r = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
    assert r["result"]["protocolVersion"] == "2025-06-18"
    assert "Has that changed?" in r["result"]["instructions"]
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = [t["name"] for t in handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
    assert names == ["remember", "search", "context", "answer", "check", "forget", "explain", "settings"]
    assert handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"] == -32601


def test_remember_question_answer(home):
    call("remember", text="I live in Toronto")
    out, _ = call("remember", text="I live in Berlin")
    assert out["questions"][0]["ask_the_user"].startswith("You said before that you live in Toronto")
    out, _ = call("answer", answer="yes")
    assert out["now_believed"] == "I live in Berlin"
    out, _ = call("search", query="where does the user live")
    assert [r["text"] for r in out["results"]] == ["I live in Berlin"]
    ctx, _ = call("context")
    assert "I live in Berlin" in ctx


def test_check_forget_settings(home):
    out, _ = call("check", text="The port is 8080.")
    assert out["ok"] is True
    call("remember", text="The port is 8080", source="assistant")
    out, _ = call("check", text="The port is 3000.")
    assert out["ok"] is False and out["conflicts"][0]["kind"] == "self"
    call("remember", text="I'm vegetarian")
    out, _ = call("forget", target="vegetarian")
    assert out["forgotten"]["text"] == "I'm vegetarian"
    out, _ = call("settings", auto_confirm=True)
    assert out["auto_confirm"] is True
    out, err = call("answer", answer="yes")
    assert err and "no open question" in out["error"]


def test_stdio_transport(home):
    inp = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n\n{"jsonrpc":"2.0","method":"x"}\nnot json\n')
    out = io.BytesIO()
    serve(stdin=inp, stdout=out)
    lines = [json.loads(x) for x in out.getvalue().decode().splitlines()]
    assert lines[0] == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert lines[1]["error"]["code"] == -32700
