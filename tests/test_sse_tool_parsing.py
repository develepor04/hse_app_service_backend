"""Tests for the streaming tool-use parser in the chat path.

`_parse_anthropic_sse` has to do two jobs at once: yield text deltas for the
client as they arrive, and quietly reassemble the assistant turn so the tool
loop can run the SQL and continue. The subtle part is that tool arguments
arrive as `input_json_delta` fragments that are not individually valid JSON —
buffering them per block index is what makes the SQL come out intact.

    cd backend && python3.11 -m pytest tests/test_sse_tool_parsing.py -q
"""
import json

from app.controllers.ai import _parse_anthropic_sse


def sse(*events: tuple[str, dict]) -> list[str]:
    """Render (event_name, payload) pairs as raw SSE lines."""
    lines: list[str] = []
    for name, payload in events:
        lines.append(f"event: {name}")
        lines.append(f"data: {json.dumps(payload)}")
        lines.append("")
    return lines


def test_text_only_stream_yields_text_and_no_tool_use():
    lines = sse(
        ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "Hello "}}),
        ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "world"}}),
        ("content_block_stop", {"index": 0}),
        ("message_delta", {"delta": {"stop_reason": "end_turn"}}),
    )
    state: dict = {}
    assert "".join(_parse_anthropic_sse(lines, state)) == "Hello world"
    assert state["stop_reason"] == "end_turn"
    assert state["content"] == [{"type": "text", "text": "Hello world"}]


def test_tool_use_arguments_are_reassembled_from_fragments():
    """The SQL arrives in pieces that are individually invalid JSON."""
    sql = "SELECT COUNT(*) AS c FROM incidents WHERE organisation_id = :org_id"
    full = json.dumps({"sql": sql})
    third = len(full) // 3
    fragments = [full[:third], full[third:third * 2], full[third * 2:]]

    lines = sse(
        ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "Let me check."}}),
        ("content_block_stop", {"index": 0}),
        ("content_block_start", {
            "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "run_sql_query", "input": {}},
        }),
        *[("content_block_delta", {"index": 1, "delta": {"type": "input_json_delta", "partial_json": f}})
          for f in fragments],
        ("content_block_stop", {"index": 1}),
        ("message_delta", {"delta": {"stop_reason": "tool_use"}}),
    )

    state: dict = {}
    text = "".join(_parse_anthropic_sse(lines, state))

    # The client still sees the preamble text stream normally.
    assert text == "Let me check."
    assert state["stop_reason"] == "tool_use"

    tool = state["content"][1]
    assert tool["type"] == "tool_use"
    assert tool["id"] == "toolu_1"
    assert tool["input"]["sql"] == sql


def test_block_order_is_preserved():
    lines = sse(
        ("content_block_start", {"index": 1, "content_block": {"type": "text", "text": "second"}}),
        ("content_block_stop", {"index": 1}),
        ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": "first"}}),
        ("content_block_stop", {"index": 0}),
    )
    state: dict = {}
    list(_parse_anthropic_sse(lines, state))
    assert [b["text"] for b in state["content"]] == ["first", "second"]


def test_malformed_tool_arguments_do_not_crash():
    """A truncated stream must leave a usable block so the loop can report an
    error to Claude rather than raising out of the generator."""
    lines = sse(
        ("content_block_start", {
            "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_x", "name": "run_sql_query", "input": {}},
        }),
        ("content_block_delta",
         {"index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"sql": "SEL'}}),
        ("content_block_stop", {"index": 0}),
        ("message_delta", {"delta": {"stop_reason": "tool_use"}}),
    )
    state: dict = {}
    list(_parse_anthropic_sse(lines, state))
    assert state["content"][0]["input"] == {}


def test_state_is_optional_for_plain_text_streaming():
    """Callers that only want deltas (no tools) pass no state at all."""
    lines = sse(
        ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "hi"}}),
    )
    assert "".join(_parse_anthropic_sse(lines)) == "hi"
