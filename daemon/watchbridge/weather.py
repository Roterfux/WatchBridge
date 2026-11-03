# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weather from Open-Meteo (no API key needed), converted for the watch."""

import json
import logging
import math
import time
import urllib.parse
import urllib.request

from .huawei.commands import Icon

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "WatchBridge/0.1 (Sailfish OS)"

# WMO weather interpretation codes -> Huawei weather icons
_WMO_ICONS = {
    0: Icon.SUNNY, 1: Icon.SUNNY, 2: Icon.CLOUDY, 3: Icon.OVERCAST,
    45: Icon.FOG, 48: Icon.FOG,
    51: Icon.LIGHT_RAIN, 53: Icon.LIGHT_RAIN, 55: Icon.RAIN,
    56: Icon.FREEZING_RAIN, 57: Icon.FREEZING_RAIN,
    61: Icon.LIGHT_RAIN, 63: Icon.RAIN, 65: Icon.HEAVY_RAIN,
    66: Icon.FREEZING_RAIN, 67: Icon.FREEZING_RAIN,
    71: Icon.LIGHT_SNOW, 73: Icon.SNOW, 75: Icon.HEAVY_SNOW, 77: Icon.SNOW_FLURRIES,
    80: Icon.SHOWERS, 81: Icon.SHOWERS, 82: Icon.RAIN_STORM,
    85: Icon.SNOW_FLURRIES, 86: Icon.SNOWSTORMS,
    95: Icon.THUNDERSTORMS, 96: Icon.THUNDER_AND_HAIL, 99: Icon.THUNDER_AND_HAIL,
}

# Short English descriptions for the UI
WMO_TEXT = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Rain showers", 81: "Rain showers",
    82: "Violent showers", 85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorm",
    96: "Thunderstorm, hail", 99: "Thunderstorm, hail",
}

_BEAUFORT_KMH = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]


def wmo_to_icon(code):
    if code is None:
        return Icon.UNKNOWN
    return _WMO_ICONS.get(int(code), Icon.UNKNOWN)


def beaufort(kmh):
    if kmh is None:
        return 0
    for i, limit in enumerate(_BEAUFORT_KMH):
        if kmh < limit:
            return i
    return 12


def moon_phase(ts):
    """Huawei moon phase byte (1 new .. 8 waning crescent) for a unix time."""
    synodic = 29.530588853
    days = (ts / 86400.0) - 10962.6  # days since the 2000-01-06 new moon (unix epoch based)
    deg = ((days % synodic) / synodic) * 360.0
    leeway = 6
    if deg >= 360 - leeway or deg <= leeway:
        return 1
    if deg < 90:
        return 2
    if deg <= 90 + leeway:
        return 3
    if deg < 180 - leeway:
        return 4
    if deg <= 180 + leeway:
        return 5
    if deg < 270 - leeway:
        return 6
    if deg <= 270 + leeway:
        return 7
    return 8


def _r(v):
    return None if v is None else int(round(v))


class Hourly:
    def __init__(self, timestamp, icon, temperature, precipitation=None, uv_index=None):
        self.timestamp = timestamp
        self.icon = icon
        self.temperature = temperature
        self.precipitation = precipitation
        self.uv_index = uv_index


class Daily:
    def __init__(self, timestamp, icon, temp_min, temp_max, sunrise=None, sunset=None, moon_phase=None, code=None):
        self.timestamp = timestamp
        self.icon = icon
        self.temp_min = temp_min
        self.temp_max = temp_max
        self.sunrise = sunrise
        self.sunset = sunset
        self.moon_phase = moon_phase
        self.code = code


class WeatherReport:
    def __init__(self):
        self.location = ""
        self.observation_time = int(time.time())
        self.code = None
        self.icon = Icon.UNKNOWN
        self.temperature = None
        self.feels_like = None
        self.temp_min = None
        self.temp_max = None
        self.humidity = None
        self.wind_speed = None      # km/h (or mph when fahrenheit)
        self.wind_beaufort = None
        self.wind_direction = None
        self.uv_index = None
        self.fahrenheit = False
        self.source = "Open-Meteo"
        self.hourly = []
        self.daily = []

    def to_dict(self):
        return {
            "location": self.location,
            "time": self.observation_time,
            "code": self.code,
            "description": WMO_TEXT.get(self.code, ""),
            "temperature": self.temperature,
            "feelsLike": self.feels_like,
            "min": self.temp_min,
            "max": self.temp_max,
            "humidity": self.humidity,
            "windSpeed": self.wind_speed,
            "windDirection": self.wind_direction,
            "uvIndex": self.uv_index,
            "unit": "F" if self.fahrenheit else "C",
            "daily": [{"time": d.timestamp, "code": d.code, "min": d.temp_min, "max": d.temp_max,
                       "description": WMO_TEXT.get(d.code, "")} for d in self.daily],
        }


def parse_open_meteo(data, location_name, fahrenheit=False, now=None):
    now = int(now if now is not None else time.time())
    r = WeatherReport()
    r.location = location_name
    r.fahrenheit = fahrenheit
    cur = data.get("current", {})
    r.observation_time = int(cur.get("time", now))
    r.code = cur.get("weather_code")
    r.icon = wmo_to_icon(r.code)
    r.temperature = _r(cur.get("temperature_2m"))
    r.feels_like = _r(cur.get("apparent_temperature"))
    r.humidity = _r(cur.get("relative_humidity_2m"))
    r.wind_speed = cur.get("wind_speed_10m")
    r.wind_direction = _r(cur.get("wind_direction_10m"))
    kmh = r.wind_speed * 1.609344 if (r.wind_speed is not None and fahrenheit) else r.wind_speed
    r.wind_beaufort = beaufort(kmh)
    r.uv_index = cur.get("uv_index")

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    for i, ts in enumerate(times):
        if ts + 3600 <= now:
            continue
        if len(r.hourly) >= 24:
            break

        def col(name):
            vals = hourly.get(name) or []
            return vals[i] if i < len(vals) else None

        r.hourly.append(Hourly(int(ts), wmo_to_icon(col("weather_code")), _r(col("temperature_2m")),
                               _r(col("precipitation_probability")), col("uv_index")))

    daily = data.get("daily", {})
    for i, ts in enumerate(daily.get("time", [])):
        def dcol(name):
            vals = daily.get(name) or []
            return vals[i] if i < len(vals) else None

        if ts + 86400 <= now:
            continue
        code = dcol("weather_code")
        d = Daily(int(ts), wmo_to_icon(code), _r(dcol("temperature_2m_min")), _r(dcol("temperature_2m_max")),
                  dcol("sunrise"), dcol("sunset"), moon_phase(ts + 43200), code)
        if d.sunrise is not None:
            d.sunrise = int(d.sunrise)
        if d.sunset is not None:
            d.sunset = int(d.sunset)
        r.daily.append(d)
    if r.daily:
        # The watch wants "today" stamped with the observation time (as Gadgetbridge does)
        r.daily[0].timestamp = r.observation_time
        r.temp_min, r.temp_max = r.daily[0].temp_min, r.daily[0].temp_max
    return r


def fetch(latitude, longitude, location_name, fahrenheit=False, timeout=20):
    if latitude is None or longitude is None or math.isnan(latitude) or math.isnan(longitude):
        raise ValueError("No weather location configured")
    query = {
        "latitude": "%.4f" % latitude,
        "longitude": "%.4f" % longitude,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,"
                   "wind_speed_10m,wind_direction_10m,uv_index",
        "hourly": "temperature_2m,weather_code,precipitation_probability,uv_index",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset",
        "timezone": "auto",
        "timeformat": "unixtime",
        "forecast_days": 8,
    }
    if fahrenheit:
        query["temperature_unit"] = "fahrenheit"
        query["wind_speed_unit"] = "mph"
    url = FORECAST_URL + "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return parse_open_meteo(data, location_name, fahrenheit)
