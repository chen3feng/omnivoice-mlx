import pytest

from omnivoice import public_tools as pt


def names(tools):
    return [tool["function"]["name"] for tool in tools]


def test_select_tools_weather():
    assert "get_weather" in names(pt.select_tools("北京今天天气怎么样？"))
    assert "get_forecast" in names(pt.select_tools("上海明天会下雨吗？"))


def test_select_tools_flight_and_exchange():
    assert names(pt.select_tools("TVF6410 现在飞到哪了？")) == ["get_flight"]
    assert names(pt.select_tools("美元兑人民币汇率是多少？")) == ["get_exchange_rate"]


def test_select_tools_falls_back_to_core_for_chat():
    assert names(pt.select_tools("给我讲个笑话")) == [
        "get_weather",
        "get_wikipedia",
        "search_web",
    ]


def test_execute_tool_unknown_name_is_safe():
    assert pt.execute_tool({"name": "does_not_exist"}) == {"error": "Unknown tool: does_not_exist"}


def test_forecast_always_has_today_tomorrow_and_day_after(monkeypatch):
    monkeypatch.setattr(
        pt,
        "geocode",
        lambda city: {"name": city, "country": "中国", "latitude": 1, "longitude": 2},
    )
    monkeypatch.setattr(
        pt,
        "http_json",
        lambda url, timeout=20: {
            "daily": {
                "time": ["2026-11-09", "2026-11-10", "2026-11-11"],
                "weather_code": [51, 3, 3],
                "temperature_2m_max": [15.0, 14.7, 18.2],
                "temperature_2m_min": [7.5, 7.0, 8.8],
                "precipitation_probability_max": [79, 0, 0],
                "wind_speed_10m_max": [26.1, 15.0, 10.0],
            }
        },
    )

    result = pt.get_forecast("上海", 1)

    assert [day["day_label"] for day in result["days"]] == ["今天", "明天", "后天"]
    assert result["days"][1]["precip_prob_pct"] == 0


def test_forecast_english_labels(monkeypatch):
    monkeypatch.setattr(
        pt,
        "geocode",
        lambda city: {"name": city, "country": "Japan", "latitude": 1, "longitude": 2},
    )
    monkeypatch.setattr(
        pt,
        "http_json",
        lambda url, timeout=20: {
            "daily": {
                "time": ["2026-11-09", "2026-11-10", "2026-11-11"],
                "weather_code": [0, 0, 0],
                "temperature_2m_max": [20, 21, 22],
                "temperature_2m_min": [10, 11, 12],
                "precipitation_probability_max": [0, 0, 0],
                "wind_speed_10m_max": [5, 5, 5],
            }
        },
    )

    result = pt.get_forecast("Tokyo", 1)

    assert [day["day_label"] for day in result["days"]] == [
        "today",
        "tomorrow",
        "day after tomorrow",
    ]


def test_exchange_rate_is_rounded_for_speech(monkeypatch):
    monkeypatch.setattr(
        pt,
        "http_json",
        lambda url, timeout=20: {"rates": {"CNY": 6.6713}, "date": "2026-11-06"},
    )

    result = pt.get_exchange_rate("USD", "CNY")

    assert result["rate"] == 6.67
    assert "rate_full" not in result
    assert result["inverse_rate"] == pytest.approx(0.1499)


def test_crypto_prices_are_short_but_timestamp_is_preserved(monkeypatch):
    monkeypatch.setattr(
        pt,
        "http_json",
        lambda url, timeout=20: {"bitcoin": {"usd": 74358.4567, "last_updated_at": 1234567890}},
    )

    result = pt.get_crypto_price("bitcoin", "usd")

    assert result["prices"]["bitcoin"]["usd"] == 74358.46
    assert result["prices"]["bitcoin"]["last_updated_at"] == 1234567890
