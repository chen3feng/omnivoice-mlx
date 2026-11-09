"""Keyless public-data tools for the voice assistant.

Every source here is free and needs no API key. Tools return JSON-serializable
dicts; failures return {"error": "..."} so the model can apologize instead of
crashing. Network calls are synchronous and short-lived.
"""

import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


def http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_text(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def http_bytes(url, headers=None, timeout=20):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


WMO_ZH = {
    0: "晴",
    1: "大致晴朗",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "冻雾",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "中阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "大阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}

WMO = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

_GEO_CACHE = {}
_WEATHER_CACHE = {}
_WEATHER_TTL = 60
_COUNTRY_CACHE = None


def is_chinese(text):
    return bool(re.search(r"[一-鿿]", text or ""))


def geocode(city):
    """Open-Meteo geocoding, cached. Returns name/country/lat/lon/timezone."""
    city = (city or "").strip()
    if not city:
        return None
    hit = _GEO_CACHE.get(city)
    if hit:
        return hit

    lang = "zh" if is_chinese(city) else "en"
    q = urllib.parse.quote(city)
    geo = http_json(
        f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language={lang}&format=json"
    )
    results = geo.get("results") or []
    if not results:
        return None
    g = results[0]
    info = {
        "name": g.get("name"),
        "country": g.get("country"),
        "latitude": g["latitude"],
        "longitude": g["longitude"],
        "timezone": g.get("timezone"),
    }
    _GEO_CACHE[city] = info
    return info


# ---------------------------------------------------------------------------
# Weather / air / sun
# ---------------------------------------------------------------------------


def get_weather(city):
    now = time.time()
    cached = _WEATHER_CACHE.get(city)
    if cached and now - cached[0] < _WEATHER_TTL:
        return cached[1]

    zh = is_chinese(city)
    g = geocode(city)
    if not g:
        return {"error": f"City not found: {city}"}

    fc = http_json(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={g['latitude']}&longitude={g['longitude']}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        "weather_code,wind_speed_10m&timezone=auto"
    )
    cur = fc.get("current", {})
    code = cur.get("weather_code")
    result = {
        "city": g["name"],
        "country": g["country"],
        "time": cur.get("time"),
        "temperature_c": cur.get("temperature_2m"),
        "apparent_temperature_c": cur.get("apparent_temperature"),
        "humidity_pct": cur.get("relative_humidity_2m"),
        "wind_kmh": cur.get("wind_speed_10m"),
        "condition": (WMO_ZH if zh else WMO).get(
            code, f"天气代码 {code}" if zh else f"Weather code {code}"
        ),
    }
    _WEATHER_CACHE[city] = (now, result)
    return result


def get_forecast(city, days=3):
    g = geocode(city)
    if not g:
        return {"error": f"City not found: {city}"}
    try:
        # Always return today + tomorrow + the day after, even when the model
        # asks for one day: otherwise "明天" questions get today's numbers.
        n = max(3, min(int(days), 7))
    except (TypeError, ValueError):
        n = 3
    zh = is_chinese(city)
    data = http_json(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={g['latitude']}&longitude={g['longitude']}"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,wind_speed_10m_max"
        f"&forecast_days={n}&timezone=auto"
    )
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    labels = ["今天", "明天", "后天"] if zh else ["today", "tomorrow", "day after tomorrow"]
    out = []
    for i, date in enumerate(dates):
        code = (daily.get("weather_code") or [None] * len(dates))[i]
        out.append(
            {
                "date": date,
                "day_label": labels[i] if i < len(labels) else f"day {i + 1}",
                "condition": (WMO_ZH if zh else WMO).get(code, str(code)),
                "high_c": (daily.get("temperature_2m_max") or [None] * len(dates))[i],
                "low_c": (daily.get("temperature_2m_min") or [None] * len(dates))[i],
                "precip_prob_pct": (
                    daily.get("precipitation_probability_max") or [None] * len(dates)
                )[i],
                "wind_kmh_max": (daily.get("wind_speed_10m_max") or [None] * len(dates))[i],
            }
        )
    return {"city": g["name"], "country": g["country"], "days": out}


def _aqi_level(aqi):
    if not isinstance(aqi, (int, float)):
        return None
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for sensitive groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very unhealthy"
    return "Hazardous"


def get_air_quality(city):
    g = geocode(city)
    if not g:
        return {"error": f"City not found: {city}"}
    data = http_json(
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={g['latitude']}&longitude={g['longitude']}"
        "&current=pm2_5,pm10,us_aqi,uv_index"
    )
    cur = data.get("current") or {}
    aqi = cur.get("us_aqi")
    return {
        "city": g["name"],
        "time": cur.get("time"),
        "pm2_5": cur.get("pm2_5"),
        "pm10": cur.get("pm10"),
        "us_aqi": aqi,
        "aqi_level": _aqi_level(aqi),
        "uv_index": cur.get("uv_index"),
    }


def get_sunrise_sunset(city, date=None):
    g = geocode(city)
    if not g:
        return {"error": f"City not found: {city}"}
    url = (
        f"https://api.sunrise-sunset.org/json?lat={g['latitude']}&lng={g['longitude']}&formatted=0"
    )
    if date:
        url += f"&date={urllib.parse.quote(str(date))}"
    data = http_json(url)
    r = data.get("results") or {}
    tzname = g.get("timezone")

    def local(iso):
        if not iso or not tzname:
            return None
        try:
            return datetime.fromisoformat(iso).astimezone(ZoneInfo(tzname)).strftime("%H:%M")
        except Exception:
            return None

    return {
        "city": g["name"],
        "date": date or "today",
        "timezone": tzname,
        "sunrise_local": local(r.get("sunrise")),
        "sunset_local": local(r.get("sunset")),
        "sunrise_utc": r.get("sunrise"),
        "sunset_utc": r.get("sunset"),
        "day_length_seconds": r.get("day_length"),
    }


def get_weather_alerts(city):
    g = geocode(city)
    if not g:
        return {"error": f"City not found: {city}"}
    country = (g.get("country") or "").lower()
    if country not in ("united states", "usa", "us"):
        return {
            "supported": False,
            "city": g["name"],
            "note": "NWS alerts are US-only.",
        }
    data = http_json(
        f"https://api.weather.gov/alerts/active?point={g['latitude']},{g['longitude']}"
    )
    alerts = []
    for f in (data.get("features") or [])[:5]:
        p = f.get("properties") or {}
        alerts.append(
            {
                "event": p.get("event"),
                "severity": p.get("severity"),
                "headline": p.get("headline"),
                "area": p.get("areaDesc"),
                "effective": p.get("effective"),
                "expires": p.get("expires"),
            }
        )
    return {"city": g["name"], "count": len(alerts), "alerts": alerts}


# ---------------------------------------------------------------------------
# Flight / time / money
# ---------------------------------------------------------------------------


def _compass(deg):
    if not isinstance(deg, (int, float)):
        return None
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int((deg + 22.5) % 360 // 45)]


def get_flight(callsign):
    cs = re.sub(r"[^A-Za-z0-9]", "", callsign or "").upper()
    if not cs:
        return {"error": "No flight number provided."}
    try:
        data = http_json(f"https://api.adsb.lol/v2/callsign/{urllib.parse.quote(cs)}")
    except Exception as exc:
        return {"error": f"Flight service unavailable: {exc}"}

    ac = data.get("ac") or []
    if not ac:
        return {
            "found": False,
            "callsign": cs,
            "note": "No live ADS-B signal. The flight may not be airborne, or the callsign may be wrong.",
        }

    a = next(
        (x for x in ac if x.get("lat") is not None and x.get("lon") is not None),
        ac[0],
    )
    alt = a.get("alt_baro")
    on_ground = alt == "ground"
    alt_ft = alt if isinstance(alt, (int, float)) else None
    gs = a.get("gs")
    track = a.get("track")
    return {
        "found": True,
        "callsign": (a.get("flight") or cs).strip(),
        "registration": a.get("r"),
        "aircraft_type": a.get("t"),
        "on_ground": on_ground,
        "altitude_ft": alt_ft,
        "altitude_m": round(alt_ft * 0.3048) if alt_ft is not None else None,
        "ground_speed_kt": gs,
        "ground_speed_kmh": round(gs * 1.852) if isinstance(gs, (int, float)) else None,
        "heading_deg": track,
        "heading": _compass(track),
        "latitude": a.get("lat"),
        "longitude": a.get("lon"),
        "squawk": a.get("squawk"),
        "seen_seconds": a.get("seen_pos"),
        "source": "adsb.lol live ADS-B",
    }


def get_time(city=""):
    city = (city or "").strip()
    if city and city.lower() not in ("local", "here", "本地", "这里", "现在"):
        g = geocode(city)
        if not g:
            return {"error": f"City not found: {city}"}
        tzname = g.get("timezone")
        if not tzname:
            return {"error": f"No timezone found for {city}"}
        try:
            now = datetime.now(ZoneInfo(tzname))
        except Exception as exc:
            return {"error": f"Cannot resolve timezone {tzname}: {exc}"}
        place = g["name"]
    else:
        now = datetime.now().astimezone()
        tzname = str(now.tzinfo)
        place = "local"

    return {
        "city": place,
        "timezone": tzname,
        "local_time": now.strftime("%Y-%m-%d %H:%M"),
        "weekday": now.strftime("%A"),
        "utc_offset": now.strftime("%z"),
    }


CURRENCY_ALIASES = {
    "美元": "USD",
    "美金": "USD",
    "dollar": "USD",
    "usd": "USD",
    "人民币": "CNY",
    "元": "CNY",
    "rmb": "CNY",
    "yuan": "CNY",
    "cny": "CNY",
    "欧元": "EUR",
    "euro": "EUR",
    "eur": "EUR",
    "日元": "JPY",
    "yen": "JPY",
    "jpy": "JPY",
    "英镑": "GBP",
    "pound": "GBP",
    "gbp": "GBP",
    "港币": "HKD",
    "港元": "HKD",
    "hkd": "HKD",
    "韩元": "KRW",
    "krw": "KRW",
    "加元": "CAD",
    "cad": "CAD",
    "澳元": "AUD",
    "aud": "AUD",
    "瑞士法郎": "CHF",
    "chf": "CHF",
}


def get_exchange_rate(from_currency="USD", to_currency="CNY"):
    def norm(value, default):
        value = (value or default).strip()
        return CURRENCY_ALIASES.get(value.lower(), value.upper())

    src = norm(from_currency, "USD")
    dst = norm(to_currency, "CNY")
    if len(src) != 3 or len(dst) != 3:
        return {"error": "Use 3-letter currency codes, e.g. USD, CNY, EUR, JPY."}
    if src == dst:
        return {"base": src, "quote": dst, "rate": 1.0, "note": "Same currency."}
    try:
        data = http_json(f"https://api.frankfurter.app/latest?from={src}&to={dst}")
    except Exception as exc:
        return {"error": f"Exchange-rate service unavailable or unsupported pair: {exc}"}
    rate = (data.get("rates") or {}).get(dst)
    if rate is None:
        return {"error": f"No rate for {src}->{dst}. Frankfurter covers ECB reference currencies."}
    # Speak a short rate: 6.6713 -> 6.67.  Do not also expose the full value:
    # MiniCPM reads the most precise field it sees and says all four digits.
    spoken = round(rate, 2) if rate >= 1 else round(rate, 4)
    return {
        "base": src,
        "quote": dst,
        "rate": spoken,
        "inverse_rate": round(1 / rate, 4) if rate else None,
        "date": data.get("date"),
        "source": "Frankfurter / ECB",
    }


CRYPTO_ALIASES = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "doge": "dogecoin",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "ada": "cardano",
    "usdt": "tether",
    "usdc": "usd-coin",
    "比特币": "bitcoin",
    "以太坊": "ethereum",
}


def get_crypto_price(coins="bitcoin,ethereum", currency="USD"):
    raw = [c.strip().lower() for c in str(coins or "").replace("，", ",").split(",") if c.strip()]
    ids = [CRYPTO_ALIASES.get(c, c) for c in raw]
    if not ids:
        return {"error": "No coin provided."}
    vs = str(currency or "usd").strip().lower()
    try:
        data = http_json(
            "https://api.coingecko.com/api/v3/simple/price"
            f"?ids={','.join(ids)}&vs_currencies={vs}&include_last_updated_at=true"
        )
    except Exception as exc:
        return {"error": f"Crypto price service unavailable: {exc}"}
    prices = {}
    for coin, vals in (data or {}).items():
        vals = dict(vals or {})
        for key, value in list(vals.items()):
            if key == "last_updated_at" or not isinstance(value, (int, float)):
                continue
            # Keep spoken prices short: 104123.4567 -> 104123.46,
            # 0.000012345 -> 0.000012.
            vals[key] = round(value, 2) if value >= 1 else round(value, 6)
        prices[coin] = vals
    return {"currency": vs.upper(), "prices": prices}


STOCK_ALIASES = {
    "贵州茅台": "600519",
    "茅台": "600519",
    "腾讯": "00700",
    "腾讯控股": "00700",
    "苹果": "AAPL",
    "特斯拉": "TSLA",
    "英伟达": "NVDA",
    "微软": "MSFT",
    "阿里巴巴": "BABA",
    "京东": "JD",
    "比亚迪": "002594",
    "宁德时代": "300750",
    "招商银行": "600036",
    "工商银行": "601398",
    "中国平安": "601318",
}


def _tencent_symbol(symbol):
    s = symbol.strip().upper().replace(" ", "")
    if s.startswith(("SH", "SZ", "BJ", "HK", "US")):
        return s.lower()
    if s.endswith(".SS"):
        return "sh" + s[:-3]
    if s.endswith(".SZ"):
        return "sz" + s[:-3]
    if s.endswith(".HK"):
        return "hk" + s[:-3].zfill(5)
    if s.isdigit():
        if len(s) == 6:
            if s[0] == "6":
                return "sh" + s
            if s[0] in "03":
                return "sz" + s
            if s[0] in "48":
                return "bj" + s
        if len(s) == 5:
            return "hk" + s
    return "us" + s


def _num(value):
    try:
        return float(str(value).replace(",", "").replace("$", "").replace("+", ""))
    except (TypeError, ValueError):
        return None


def get_stock_quote(symbol):
    """Keyless quote: Tencent (A/HK/US), then Nasdaq for US symbols."""
    sym = (symbol or "").strip()
    if not sym:
        return {"error": "No stock symbol provided."}
    sym = STOCK_ALIASES.get(sym, sym)
    code = _tencent_symbol(sym)

    try:
        raw = http_bytes(
            f"https://qt.gtimg.cn/q={code}",
            headers={"Referer": "https://finance.qq.com/"},
        )
        text = raw.decode("gbk", "replace")
        payload = text.split('="', 1)[1].rsplit('"', 1)[0] if '="' in text else ""
        fields = payload.split("~")
        if len(fields) >= 35 and fields[3]:
            currency = (
                "CNY"
                if code.startswith(("sh", "sz", "bj"))
                else "HKD"
                if code.startswith("hk")
                else "USD"
            )
            return {
                "symbol": (fields[2] or sym).upper(),
                "name": fields[1],
                "price": _num(fields[3]),
                "previous_close": _num(fields[4]),
                "change": _num(fields[31]),
                "change_pct": _num(fields[32]),
                "open": _num(fields[5]),
                "high": _num(fields[33]),
                "low": _num(fields[34]),
                "currency": currency,
                "market_time": fields[30],
                "source": "Tencent quote",
            }
    except Exception:
        pass

    # US fallback: Nasdaq's public quote endpoint.
    try:
        data = http_json(
            "https://api.nasdaq.com/api/quote/"
            f"{urllib.parse.quote(sym.upper())}/info?assetclass=stocks"
        )
        d = data.get("data") or {}
        p = d.get("primaryData") or {}
        if not d.get("symbol") and not p.get("lastSalePrice"):
            return {"error": f"No quote found for {sym}."}
        pct = p.get("percentageChange")
        return {
            "symbol": d.get("symbol") or sym.upper(),
            "name": d.get("companyName"),
            "price": _num(p.get("lastSalePrice")),
            "previous_close": None,
            "change": _num(p.get("netChange")),
            "change_pct": _num(str(pct).replace("%", "")) if pct else None,
            "open": None,
            "high": None,
            "low": None,
            "currency": "USD",
            "market_time": p.get("lastTradeTimestamp"),
            "source": "Nasdaq",
        }
    except Exception as exc:
        return {"error": f"No quote found for {sym}: {exc}"}


# ---------------------------------------------------------------------------
# Knowledge / news / reference
# ---------------------------------------------------------------------------


def get_wikipedia(topic):
    topic = (topic or "").strip()
    if not topic:
        return {"error": "No topic provided."}
    langs = ["zh", "en"] if is_chinese(topic) else ["en", "zh"]
    for lang in langs:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(topic)}"
        try:
            data = http_json(url)
        except Exception:
            continue
        if data.get("type") == "disambiguation":
            continue
        extract = (data.get("extract") or "").strip()
        if not extract:
            continue
        page = (data.get("content_urls", {}).get("desktop", {}) or {}).get("page")
        return {
            "found": True,
            "language": lang,
            "title": data.get("title"),
            "extract": extract[:500],
            "url": page,
        }
    return {"found": False, "topic": topic, "note": "No Wikipedia summary found."}


def search_web(query):
    q = urllib.parse.quote(query or "")
    try:
        data = http_json(f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1")
    except Exception as exc:
        return {"error": f"Search service unavailable: {exc}"}
    related = []
    for item in (data.get("RelatedTopics") or [])[:3]:
        if item.get("Text"):
            related.append({"text": item.get("Text"), "url": item.get("FirstURL")})
    out = {
        "query": query,
        "abstract": data.get("AbstractText"),
        "abstract_url": data.get("AbstractURL"),
        "answer": data.get("Answer"),
        "definition": data.get("Definition"),
        "related": related,
    }
    if not any([out["abstract"], out["answer"], out["definition"], related]):
        out["found"] = False
        out["note"] = "No instant answer; try get_wikipedia."
    return out


def _parse_arxiv(xml_text, limit=3):
    root = ET.fromstring(xml_text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for entry in root.findall("a:entry", ns)[:limit]:
        out.append(
            {
                "title": " ".join((entry.findtext("a:title", "", ns) or "").split()),
                "summary": " ".join((entry.findtext("a:summary", "", ns) or "").split())[:400],
                "published": entry.findtext("a:published", "", ns),
                "url": entry.findtext("a:id", "", ns),
            }
        )
    return out


def search_arxiv(query, limit=3):
    q = urllib.parse.quote_plus(f"all:{query or ''}")
    try:
        xml_text = http_text(
            f"http://export.arxiv.org/api/query?search_query={q}&max_results={limit}"
        )
        return {"query": query, "papers": _parse_arxiv(xml_text, limit)}
    except Exception as exc:
        return {"error": f"arXiv unavailable: {exc}"}


def search_books(query, limit=3):
    try:
        data = http_json(
            f"https://openlibrary.org/search.json?q={urllib.parse.quote(query or '')}&limit={limit}"
        )
    except Exception as exc:
        return {"error": f"Open Library unavailable: {exc}"}
    out = []
    for d in (data.get("docs") or [])[:limit]:
        key = d.get("key")
        out.append(
            {
                "title": d.get("title"),
                "authors": (d.get("author_name") or [])[:3],
                "first_publish_year": d.get("first_publish_year"),
                "url": f"https://openlibrary.org{key}" if key else None,
            }
        )
    return {"query": query, "books": out}


def search_pubmed(query, limit=3):
    q = urllib.parse.quote(query or "")
    try:
        search = http_json(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            f"?db=pubmed&term={q}&retmode=json&retmax={limit}"
        )
    except Exception as exc:
        return {"error": f"PubMed unavailable: {exc}"}
    ids = (search.get("esearchresult") or {}).get("idlist") or []
    if not ids:
        return {"query": query, "count": 0, "articles": []}
    try:
        summary = http_json(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            f"?db=pubmed&id={','.join(ids)}&retmode=json"
        )
    except Exception as exc:
        return {"error": f"PubMed summary unavailable: {exc}"}
    result = summary.get("result") or {}
    articles = []
    for pid in ids:
        row = result.get(pid) or {}
        articles.append(
            {
                "pmid": pid,
                "title": row.get("title"),
                "journal": row.get("fulljournalname") or row.get("source"),
                "pubdate": row.get("pubdate"),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            }
        )
    return {"query": query, "count": len(articles), "articles": articles}


def search_literature(source, query):
    source = (source or "books").strip().lower()
    if source == "books":
        return search_books(query)
    if source == "arxiv":
        return search_arxiv(query)
    if source == "pubmed":
        return search_pubmed(query)
    return {"error": "source must be books, arxiv, or pubmed."}


def _parse_rss(xml_text, limit=5):
    root = ET.fromstring(xml_text)
    out = []
    for item in root.findall(".//item")[:limit]:
        out.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "published": (item.findtext("pubDate") or "").strip(),
                "source": (item.findtext("source") or "").strip(),
            }
        )
    return out


def get_news(query):
    q = urllib.parse.quote(query or "top news")
    if is_chinese(query or ""):
        url = f"https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    else:
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        return {"query": query, "articles": _parse_rss(http_text(url), 5)}
    except Exception as exc:
        return {"error": f"News service unavailable: {exc}"}


def search_places(query):
    q = urllib.parse.quote(query or "")
    try:
        data = http_json(
            f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=3&addressdetails=0"
        )
    except Exception as exc:
        return {"error": f"OpenStreetMap unavailable: {exc}"}
    places = []
    for r in (data or [])[:3]:
        places.append(
            {
                "name": r.get("name"),
                "display_name": r.get("display_name"),
                "latitude": r.get("lat"),
                "longitude": r.get("lon"),
                "type": r.get("type"),
                "class": r.get("class"),
            }
        )
    return {"query": query, "places": places}


# ---------------------------------------------------------------------------
# Countries / holidays / recipes / sports / dictionary
# ---------------------------------------------------------------------------

COUNTRY_ALIASES = {
    "中国": "CHN",
    "中华人民共和国": "CHN",
    "china": "CHN",
    "美国": "USA",
    "united states": "USA",
    "usa": "USA",
    "us": "USA",
    "日本": "JPN",
    "japan": "JPN",
    "英国": "GBR",
    "united kingdom": "GBR",
    "uk": "GBR",
    "法国": "FRA",
    "france": "FRA",
    "德国": "DEU",
    "germany": "DEU",
    "印度": "IND",
    "india": "IND",
    "俄罗斯": "RUS",
    "russia": "RUS",
    "加拿大": "CAN",
    "canada": "CAN",
    "澳大利亚": "AUS",
    "australia": "AUS",
    "巴西": "BRA",
    "brazil": "BRA",
    "韩国": "KOR",
    "south korea": "KOR",
    "意大利": "ITA",
    "italy": "ITA",
    "西班牙": "ESP",
    "spain": "ESP",
    "新加坡": "SGP",
    "singapore": "SGP",
    "泰国": "THA",
    "thailand": "THA",
}


def _world_countries():
    global _COUNTRY_CACHE
    if _COUNTRY_CACHE is None:
        data = http_json("https://api.worldbank.org/v2/country?format=json&per_page=300")
        _COUNTRY_CACHE = data[1] if isinstance(data, list) and len(data) > 1 else []
    return _COUNTRY_CACHE


def resolve_country(country):
    c = (country or "").strip()
    if not c:
        return None
    alias = COUNTRY_ALIASES.get(c.lower()) or COUNTRY_ALIASES.get(c)
    if alias:
        c = alias
    up = c.upper()
    for row in _world_countries():
        if (
            row.get("id") == up
            or row.get("iso2Code") == up
            or (row.get("name") or "").lower() == c.lower()
        ):
            return row
    return None


def get_country_info(country):
    row = resolve_country(country)
    if not row:
        return {"error": f"Country not found: {country}"}
    iso3 = row.get("id")
    population = None
    try:
        p = http_json(
            "https://api.worldbank.org/v2/country/"
            f"{iso3}/indicator/SP.POP.TOTL?format=json&per_page=1&date=2024"
        )
        if isinstance(p, list) and len(p) > 1 and p[1]:
            population = p[1][0].get("value")
    except Exception:
        pass
    return {
        "name": row.get("name"),
        "iso2": row.get("iso2Code"),
        "iso3": iso3,
        "capital": row.get("capitalCity"),
        "region": (row.get("region") or {}).get("value"),
        "income_level": (row.get("incomeLevel") or {}).get("value"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "population_2024": population,
    }


HOLIDAY_COUNTRY_ALIASES = {
    "中国": "CN",
    "美国": "US",
    "日本": "JP",
    "英国": "GB",
    "法国": "FR",
    "德国": "DE",
    "韩国": "KR",
    "印度": "IN",
    "加拿大": "CA",
    "澳大利亚": "AU",
    "巴西": "BR",
    "新加坡": "SG",
    "china": "CN",
    "usa": "US",
    "japan": "JP",
    "uk": "GB",
}


def get_holidays(country="CN", year=None):
    raw = (country or "CN").strip()
    code = HOLIDAY_COUNTRY_ALIASES.get(raw.lower(), HOLIDAY_COUNTRY_ALIASES.get(raw, raw.upper()))
    try:
        y = int(year) if year else datetime.now().year
    except (TypeError, ValueError):
        y = datetime.now().year
    try:
        data = http_json(f"https://date.nager.at/api/v3/PublicHolidays/{y}/{code}")
    except Exception as exc:
        return {"error": f"Holiday service unavailable or unknown country: {exc}"}
    if not isinstance(data, list):
        return {"error": f"No holiday data for {code} in {y}."}
    return {
        "country": code,
        "year": y,
        "holidays": [
            {
                "date": h.get("date"),
                "local_name": h.get("localName"),
                "name": h.get("name"),
                "global": h.get("global"),
            }
            for h in data[:12]
        ],
    }


def search_recipes(query):
    try:
        data = http_json(
            "https://www.themealdb.com/api/json/v1/1/search.php?s="
            f"{urllib.parse.quote(query or '')}"
        )
    except Exception as exc:
        return {"error": f"Recipe service unavailable: {exc}"}
    meals = data.get("meals") or []
    out = []
    for m in meals[:3]:
        ingredients = []
        for i in range(1, 21):
            ing = (m.get(f"strIngredient{i}") or "").strip()
            meas = (m.get(f"strMeasure{i}") or "").strip()
            if ing:
                ingredients.append(f"{meas} {ing}".strip())
        out.append(
            {
                "name": m.get("strMeal"),
                "category": m.get("strCategory"),
                "area": m.get("strArea"),
                "instructions": (m.get("strInstructions") or "")[:400],
                "ingredients": ingredients[:12],
                "youtube": m.get("strYoutube"),
            }
        )
    return {"query": query, "meals": out}


SPORTS_LEAGUES = {
    "nba": ("basketball", "nba"),
    "nfl": ("football", "nfl"),
    "mlb": ("baseball", "mlb"),
    "nhl": ("hockey", "nhl"),
    "epl": ("soccer", "eng.1"),
    "premier league": ("soccer", "eng.1"),
    "英超": ("soccer", "eng.1"),
    "laliga": ("soccer", "esp.1"),
    "la liga": ("soccer", "esp.1"),
    "西甲": ("soccer", "esp.1"),
    "champions": ("soccer", "uefa.champions"),
    "champions league": ("soccer", "uefa.champions"),
    "欧冠": ("soccer", "uefa.champions"),
    "cba": ("basketball", "cba"),
    "中超": ("soccer", "chn.1"),
}


def get_sports_scores(league="nba"):
    key = (league or "nba").strip().lower()
    sport, slug = SPORTS_LEAGUES.get(key, ("basketball", "nba"))
    try:
        data = http_json(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{slug}/scoreboard")
    except Exception as exc:
        return {"error": f"Sports service unavailable: {exc}"}
    events = []
    for e in (data.get("events") or [])[:5]:
        comp = (e.get("competitions") or [{}])[0]
        status = (comp.get("status") or {}).get("type") or {}
        teams = []
        for c in comp.get("competitors") or []:
            team = c.get("team") or {}
            teams.append(
                {
                    "team": team.get("displayName"),
                    "score": c.get("score"),
                    "winner": c.get("winner"),
                }
            )
        events.append(
            {
                "name": e.get("name"),
                "date": e.get("date"),
                "status": status.get("description"),
                "completed": status.get("completed"),
                "teams": teams,
            }
        )
    return {"league": league, "events": events}


def define_word(word):
    w = (word or "").strip()
    if not w:
        return {"error": "No word provided."}
    try:
        data = http_json(f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(w)}")
    except Exception as exc:
        return {"error": f"Dictionary unavailable or word not found: {exc}"}
    entry = data[0] if isinstance(data, list) and data else {}
    phonetic = entry.get("phonetic") or next(
        (p.get("text") for p in entry.get("phonetics", []) if p.get("text")), None
    )
    meanings = []
    for m in (entry.get("meanings") or [])[:3]:
        definitions = [
            d.get("definition") for d in (m.get("definitions") or [])[:2] if d.get("definition")
        ]
        meanings.append(
            {
                "part_of_speech": m.get("partOfSpeech"),
                "definitions": definitions,
            }
        )
    return {"word": entry.get("word", w), "phonetic": phonetic, "meanings": meanings}


# ---------------------------------------------------------------------------
# Network / space
# ---------------------------------------------------------------------------


def get_ip_info(ip=""):
    target = (ip or "").strip()
    url = (
        f"https://ipapi.co/{urllib.parse.quote(target)}/json/"
        if target
        else "https://ipapi.co/json/"
    )
    try:
        data = http_json(url)
    except Exception as exc:
        return {"error": f"IP service unavailable: {exc}"}
    if data.get("error"):
        return {"error": data.get("reason") or "IP lookup failed."}
    return {
        "ip": data.get("ip"),
        "city": data.get("city"),
        "region": data.get("region"),
        "country": data.get("country_name"),
        "org": data.get("org"),
        "timezone": data.get("timezone"),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
    }


def dns_lookup(domain, record_type="A"):
    name = (domain or "").strip()
    rtype = (record_type or "A").strip().upper()
    if not name:
        return {"error": "No domain provided."}
    try:
        data = http_json(f"https://dns.google/resolve?name={urllib.parse.quote(name)}&type={rtype}")
    except Exception as exc:
        return {"error": f"DNS service unavailable: {exc}"}
    answers = [
        {
            "name": a.get("name"),
            "type": a.get("type"),
            "ttl": a.get("TTL"),
            "data": a.get("data"),
        }
        for a in (data.get("Answer") or [])
    ]
    return {
        "domain": name,
        "record_type": rtype,
        "status": data.get("Status"),
        "answers": answers,
    }


def get_space_weather():
    try:
        data = http_json("https://services.swpc.noaa.gov/products/noaa-scales.json")
    except Exception as exc:
        return {"error": f"Space-weather service unavailable: {exc}"}
    cur = data.get("0") or {}
    return {
        "updated": f"{cur.get('DateStamp')} {cur.get('TimeStamp')}".strip(),
        "radio_blackout": cur.get("R"),
        "solar_radiation": cur.get("S"),
        "geomagnetic": cur.get("G"),
        "source": "NOAA SWPC",
    }


def get_earthquakes(min_magnitude=4.5, limit=5):
    try:
        mag = float(min_magnitude)
    except (TypeError, ValueError):
        mag = 4.5
    try:
        lim = max(1, min(int(limit), 10))
    except (TypeError, ValueError):
        lim = 5
    try:
        data = http_json(
            "https://earthquake.usgs.gov/fdsnws/event/1/query"
            f"?format=geojson&minmagnitude={mag}&limit={lim}&orderby=time"
        )
    except Exception as exc:
        return {"error": f"Earthquake service unavailable: {exc}"}
    out = []
    for f in (data.get("features") or [])[:lim]:
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None, None]
        ts = p.get("time")
        out.append(
            {
                "magnitude": p.get("mag"),
                "place": p.get("place"),
                "time_utc": (
                    datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
                    if isinstance(ts, (int, float))
                    else None
                ),
                "longitude": coords[0],
                "latitude": coords[1],
                "depth_km": coords[2],
                "url": p.get("url"),
            }
        )
    return {"min_magnitude": mag, "count": len(out), "earthquakes": out}


def get_iss_location():
    try:
        data = http_json("https://api.wheretheiss.at/v1/satellites/25544")
    except Exception as exc:
        return {"error": f"ISS service unavailable: {exc}"}
    ts = data.get("timestamp")
    return {
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "altitude_km": data.get("altitude"),
        "velocity_kmh": data.get("velocity"),
        "visibility": data.get("visibility"),
        "timestamp_utc": (
            datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
            if isinstance(ts, (int, float))
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


def _tool(name, description, properties, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


TOOLS = [
    _tool(
        "get_weather",
        "Get the current real weather for a city: temperature, feels-like, humidity, wind, condition.",
        {"city": {"type": "string", "description": "City name, e.g. Tokyo or 北京"}},
        ["city"],
    ),
    _tool(
        "get_forecast",
        "Get a daily weather forecast for a city. Each entry has day_label "
        "(today/tomorrow/...) and a date; use the entry matching the user's "
        "question. Always returns at least today, tomorrow and the day after.",
        {
            "city": {"type": "string", "description": "City name"},
            "days": {
                "type": "integer",
                "description": "Days to return, 1-7 (default 3; at least 3 are returned)",
            },
        },
        ["city"],
    ),
    _tool(
        "get_air_quality",
        "Get current air quality (PM2.5, PM10, US AQI, UV index) for a city.",
        {"city": {"type": "string", "description": "City name"}},
        ["city"],
    ),
    _tool(
        "get_sunrise_sunset",
        "Get sunrise, sunset and day length for a city, optionally on a date.",
        {
            "city": {"type": "string", "description": "City name"},
            "date": {"type": "string", "description": "YYYY-MM-DD, optional"},
        },
        ["city"],
    ),
    _tool(
        "get_weather_alerts",
        "Get active weather alerts for a US city from the National Weather Service.",
        {"city": {"type": "string", "description": "US city name"}},
        ["city"],
    ),
    _tool(
        "get_flight",
        "Track a specific airborne flight by flight number/callsign, e.g. CA1234 or UA888. Returns live ADS-B position, altitude, speed and heading. Not a schedule, route or ticket search.",
        {"callsign": {"type": "string", "description": "Flight number / callsign"}},
        ["callsign"],
    ),
    _tool(
        "get_time",
        "Get the current local date and time in a city. Omit city for local time.",
        {"city": {"type": "string", "description": "City name, optional"}},
    ),
    _tool(
        "get_exchange_rate",
        "Get the latest currency exchange rate between two currencies, e.g. USD to CNY.",
        {
            "from_currency": {"type": "string", "description": "Source currency, e.g. USD or 美元"},
            "to_currency": {"type": "string", "description": "Target currency, e.g. CNY or 人民币"},
        },
        ["from_currency", "to_currency"],
    ),
    _tool(
        "get_crypto_price",
        "Get current cryptocurrency prices, e.g. bitcoin, ethereum, solana.",
        {
            "coins": {
                "type": "string",
                "description": "Comma-separated coins or symbols, e.g. bitcoin,ethereum or BTC,ETH",
            },
            "currency": {
                "type": "string",
                "description": "Quote currency, e.g. USD, CNY (default USD)",
            },
        },
        ["coins"],
    ),
    _tool(
        "get_stock_quote",
        "Get a stock quote by ticker symbol, e.g. AAPL, TSLA, 600519.SS.",
        {"symbol": {"type": "string", "description": "Ticker symbol"}},
        ["symbol"],
    ),
    _tool(
        "get_country_info",
        "Get country facts: capital, region, income level, population and coordinates.",
        {
            "country": {
                "type": "string",
                "description": "Country name or ISO code, e.g. Japan, CN, USA",
            }
        },
        ["country"],
    ),
    _tool(
        "get_wikipedia",
        "Look up a short encyclopedia summary about a person, place, thing or concept.",
        {"topic": {"type": "string", "description": "Topic, e.g. 黑洞 or Ada Lovelace"}},
        ["topic"],
    ),
    _tool(
        "search_web",
        "Get a DuckDuckGo instant answer for a question. Good for quick facts; not a full web search.",
        {"query": {"type": "string", "description": "Search query"}},
        ["query"],
    ),
    _tool(
        "search_places",
        "Search for a place, landmark or address on OpenStreetMap.",
        {"query": {"type": "string", "description": "Place or address"}},
        ["query"],
    ),
    _tool(
        "search_literature",
        "Search books, arXiv papers, or PubMed articles.",
        {
            "source": {
                "type": "string",
                "enum": ["books", "arxiv", "pubmed"],
                "description": "Where to search",
            },
            "query": {"type": "string", "description": "Search query"},
        },
        ["source", "query"],
    ),
    _tool(
        "get_news",
        "Get recent news headlines for a topic.",
        {"query": {"type": "string", "description": "News topic or keyword"}},
        ["query"],
    ),
    _tool(
        "get_holidays",
        "Get public holidays for a country and year.",
        {
            "country": {
                "type": "string",
                "description": "Country name or ISO2 code, e.g. CN, US, 日本",
            },
            "year": {"type": "integer", "description": "Year, default current year"},
        },
        ["country"],
    ),
    _tool(
        "search_recipes",
        "Search recipes by dish name. TheMealDB is English-first.",
        {"query": {"type": "string", "description": "Dish name, e.g. rice, chicken"}},
        ["query"],
    ),
    _tool(
        "get_sports_scores",
        "Get recent scores for a league: nba, nfl, mlb, nhl, epl, laliga, champions, cba, 中超.",
        {"league": {"type": "string", "description": "League alias, e.g. nba or epl"}},
        ["league"],
    ),
    _tool(
        "define_word",
        "Get English dictionary definitions, pronunciation and parts of speech.",
        {"word": {"type": "string", "description": "English word"}},
        ["word"],
    ),
    _tool(
        "get_ip_info",
        "Get geolocation and network info for an IP address, or the current public IP.",
        {"ip": {"type": "string", "description": "IPv4/IPv6 address, optional"}},
    ),
    _tool(
        "dns_lookup",
        "Resolve DNS records for a domain: A, AAAA, MX, TXT, CNAME, NS, SOA.",
        {
            "domain": {"type": "string", "description": "Domain name, e.g. example.com"},
            "record_type": {"type": "string", "description": "DNS record type (default A)"},
        },
        ["domain"],
    ),
    _tool(
        "get_space_weather",
        "Get current NOAA space-weather scales: radio blackout, solar radiation, geomagnetic storm.",
        {},
    ),
    _tool(
        "get_earthquakes",
        "Get the latest earthquakes above a magnitude threshold.",
        {
            "min_magnitude": {"type": "number", "description": "Minimum magnitude, default 4.5"},
            "limit": {"type": "integer", "description": "Number of results, 1-10 (default 5)"},
        },
    ),
    _tool(
        "get_iss_location",
        "Get the current latitude, longitude, altitude and speed of the International Space Station.",
        {},
    ),
]


TOOL_IMPL = {
    "get_weather": lambda a: get_weather(a.get("city", "")),
    "get_forecast": lambda a: get_forecast(a.get("city", ""), a.get("days", 3)),
    "get_air_quality": lambda a: get_air_quality(a.get("city", "")),
    "get_sunrise_sunset": lambda a: get_sunrise_sunset(a.get("city", ""), a.get("date")),
    "get_weather_alerts": lambda a: get_weather_alerts(a.get("city", "")),
    "get_flight": lambda a: get_flight(a.get("callsign", "")),
    "get_time": lambda a: get_time(a.get("city", "")),
    "get_exchange_rate": lambda a: get_exchange_rate(
        a.get("from_currency", "USD"), a.get("to_currency", "CNY")
    ),
    "get_crypto_price": lambda a: get_crypto_price(
        a.get("coins", "bitcoin,ethereum"), a.get("currency", "USD")
    ),
    "get_stock_quote": lambda a: get_stock_quote(a.get("symbol", "")),
    "get_country_info": lambda a: get_country_info(a.get("country", "")),
    "get_wikipedia": lambda a: get_wikipedia(a.get("topic", "")),
    "search_web": lambda a: search_web(a.get("query", "")),
    "search_places": lambda a: search_places(a.get("query", "")),
    "search_literature": lambda a: search_literature(a.get("source", "books"), a.get("query", "")),
    "get_news": lambda a: get_news(a.get("query", "")),
    "get_holidays": lambda a: get_holidays(a.get("country", "CN"), a.get("year")),
    "search_recipes": lambda a: search_recipes(a.get("query", "")),
    "get_sports_scores": lambda a: get_sports_scores(a.get("league", "nba")),
    "define_word": lambda a: define_word(a.get("word", "")),
    "get_ip_info": lambda a: get_ip_info(a.get("ip", "")),
    "dns_lookup": lambda a: dns_lookup(a.get("domain", ""), a.get("record_type", "A")),
    "get_space_weather": lambda a: get_space_weather(),
    "get_earthquakes": lambda a: get_earthquakes(a.get("min_magnitude", 4.5), a.get("limit", 5)),
    "get_iss_location": lambda a: get_iss_location(),
}


# Keyword groups used to keep the tool prompt small. Sending all 25 schemas on
# every turn is slow on 9B models; a matched subset is both faster and more
# accurate. If nothing matches we still expose a small core set so the model can
# decide to call a tool or just chat.
TOOL_GROUPS = [
    (
        (
            "天气",
            "气温",
            "温度",
            "下雨",
            "下雪",
            "晴",
            "阴",
            "风",
            "weather",
            "forecast",
            "temperature",
            "rain",
            "snow",
            "sunny",
            "cloudy",
            "wind",
        ),
        (
            "get_weather",
            "get_forecast",
            "get_air_quality",
            "get_sunrise_sunset",
            "get_weather_alerts",
        ),
    ),
    (("空气质量", "空气", "雾霾", "aqi", "pollution"), ("get_air_quality",)),
    (("日出", "日落", "sunrise", "sunset"), ("get_sunrise_sunset",)),
    (("预警", "警报", "alert", "warning"), ("get_weather_alerts",)),
    (
        (
            "航班",
            "飞机",
            "机场",
            "起飞",
            "落地",
            "飞到",
            "飞往",
            "callsign",
            "flight",
            "plane",
            "airport",
            "adsb",
        ),
        ("get_flight",),
    ),
    (("几点", "时间", "时区", "time", "timezone", "clock"), ("get_time",)),
    (
        (
            "汇率",
            "美元",
            "人民币",
            "欧元",
            "日元",
            "英镑",
            "exchange rate",
            "usd",
            "cny",
            "eur",
            "jpy",
            "gbp",
            "dollar",
            "yuan",
        ),
        ("get_exchange_rate",),
    ),
    (
        ("比特币", "以太坊", "加密货币", "btc", "eth", "bitcoin", "ethereum", "crypto"),
        ("get_crypto_price",),
    ),
    (
        (
            "股票",
            "股价",
            "股市",
            "大盘",
            "stock",
            "share price",
            "nasdaq",
            "aapl",
            "tsla",
            "腾讯",
            "茅台",
        ),
        ("get_stock_quote",),
    ),
    (("国家", "首都", "人口", "country", "capital", "population"), ("get_country_info",)),
    (("百科", "维基", "是谁", "是什么", "who is", "what is", "wikipedia"), ("get_wikipedia",)),
    (("搜索", "搜一下", "查一下", "帮我查", "search", "google", "网上"), ("search_web",)),
    (
        (
            "附近",
            "周边",
            "地点",
            "餐厅",
            "医院",
            "加油站",
            "酒店",
            "nearby",
            "restaurant",
            "hospital",
            "hotel",
            "gas station",
        ),
        ("search_places",),
    ),
    (
        ("论文", "文献", "书籍", "paper", "arxiv", "pubmed", "book", "literature"),
        ("search_literature",),
    ),
    (("新闻", "头条", "资讯", "news", "headline"), ("get_news",)),
    (("假期", "节假日", "放假", "holiday", "vacation"), ("get_holidays",)),
    (("菜谱", "食谱", "怎么做", "做法", "recipe", "cook"), ("search_recipes",)),
    (
        (
            "比分",
            "比赛",
            "赛况",
            "体育",
            "score",
            "game",
            "match",
            "nba",
            "nfl",
            "soccer",
            "football",
        ),
        ("get_sports_scores",),
    ),
    (("意思", "单词", "词典", "define", "meaning", "dictionary"), ("define_word",)),
    (("ip地址", "我的ip", "ip address", "ip 地址"), ("get_ip_info",)),
    (("dns", "域名", "domain", "解析"), ("dns_lookup",)),
    (
        ("太阳", "极光", "地磁", "太阳风", "aurora", "solar", "space weather", "geomagnetic"),
        ("get_space_weather",),
    ),
    (("地震", "震级", "earthquake"), ("get_earthquakes",)),
    (("空间站", "国际空间站", "iss", "space station"), ("get_iss_location",)),
]
CORE_TOOL_NAMES = ("get_weather", "get_wikipedia", "search_web")


def select_tools(question):
    """Return the tool schemas relevant to a question (small, ordered subset)."""
    q = (question or "").lower()
    names = set()
    for keys, group in TOOL_GROUPS:
        if any(k.lower() in q for k in keys):
            names.update(group)
    if not names:
        names.update(CORE_TOOL_NAMES)
    return [t for t in TOOLS if t["function"]["name"] in names]


def execute_tool(call):
    """Run a parsed tool call; always returns JSON-serializable data."""
    name = (call or {}).get("name")
    args = (call or {}).get("arguments") or {}
    fn = TOOL_IMPL.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(args)
    except Exception as exc:
        return {"error": f"{name} failed: {exc}"}
