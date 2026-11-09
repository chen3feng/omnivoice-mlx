from omnivoice.prompts import (
    INSTRUCTION_EN,
    INSTRUCTION_ZH,
    RETRY_EN,
    RETRY_ZH,
    ROUTER_EN,
    ROUTER_ZH,
    build_instruction,
    build_retry_instruction,
    build_router_instruction,
)


def test_build_instruction_uses_question_language():
    assert build_instruction("北京今天天气怎么样？") == INSTRUCTION_ZH
    assert build_instruction("What is the weather in Tokyo?") == INSTRUCTION_EN
    assert build_instruction(None) == INSTRUCTION_EN


def test_router_prompts_forbid_answering():
    assert "NO_TOOL" in ROUTER_ZH
    assert "NO_TOOL" in ROUTER_EN
    assert "不要回答" in ROUTER_ZH
    assert "never answer" in ROUTER_EN
    assert build_router_instruction("北京天气") == ROUTER_ZH
    assert build_router_instruction("weather in Tokyo") == ROUTER_EN


def test_retry_prompts_demand_a_tool_call():
    assert "NO_TOOL" in RETRY_ZH
    assert "NO_TOOL" in RETRY_EN
    assert build_retry_instruction("北京天气") == RETRY_ZH
    assert build_retry_instruction("weather in Tokyo") == RETRY_EN


def test_answer_prompts_limit_news_to_one_headline():
    assert "最重要的一条" in INSTRUCTION_ZH
    assert "single most" in INSTRUCTION_EN
