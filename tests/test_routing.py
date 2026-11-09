from omnivoice import routing

TOOL = '<tool_call>{"name": "get_weather", "arguments": {"city": "北京"}}</tool_call>'


def test_resolve_keeps_model_tool_call():
    call, used, retry_reply, forced = routing.resolve_decision(
        "北京天气", TOOL, lambda *_: "unused"
    )

    assert call["name"] == "get_weather"
    assert used == TOOL
    assert retry_reply is None
    assert forced is False


def test_resolve_retries_after_no_tool():
    seen = {}

    def retry(failed, instruction):
        seen["failed"] = failed
        seen["instruction"] = instruction
        return TOOL

    call, used, retry_reply, forced = routing.resolve_decision("北京天气", "NO_TOOL", retry)

    assert call["name"] == "get_weather"
    assert used == TOOL
    assert retry_reply == TOOL
    assert forced is False
    assert seen["failed"] == "NO_TOOL"
    assert "必须调用" in seen["instruction"]


def test_resolve_falls_back_when_retry_declines():
    call, used, retry_reply, forced = routing.resolve_decision(
        "北京今天天气怎么样？", "NO_TOOL", lambda *_: "NO_TOOL"
    )

    assert call == {"name": "get_weather", "arguments": {"city": "北京"}}
    assert forced is True
    assert '"get_weather"' in used
    assert retry_reply == "NO_TOOL"


def test_resolve_does_not_retry_plain_chat():
    called = False

    def retry(*_):
        nonlocal called
        called = True
        return TOOL

    call, used, retry_reply, forced = routing.resolve_decision("讲个笑话", "NO_TOOL", retry)

    assert call is None
    assert used == "NO_TOOL"
    assert retry_reply is None
    assert forced is False
    assert not called


def test_resolve_leaves_entity_tools_alone():
    call, used, retry_reply, forced = routing.resolve_decision(
        "苹果股价多少？", "NO_TOOL", lambda *_: "NO_TOOL"
    )

    assert call is None
    assert forced is False
    assert used == "NO_TOOL"
