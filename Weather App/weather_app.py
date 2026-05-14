"""A small weather app powered by pandas and the Open-Meteo API."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


WEATHER_CODES = {
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


@dataclass(frozen=True)
class Location:
    name: str
    country: str
    admin1: str
    latitude: float
    longitude: float
    timezone: str

    @property
    def display_name(self) -> str:
        parts = [self.name, self.admin1, self.country]
        return ", ".join(part for part in parts if part)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch current weather and forecast data, then analyze it with pandas."
    )
    parser.add_argument("location", nargs="?", help="City or place name, for example Warsaw")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        choices=range(1, 17),
        metavar="1-16",
        help="Number of forecast days to fetch. Default: 7",
    )
    parser.add_argument(
        "--country-code",
        help="Optional ISO country filter for geocoding, for example US, PL, GB.",
    )
    parser.add_argument(
        "--temperature-unit",
        choices=["celsius", "fahrenheit"],
        default="celsius",
        help="Temperature unit. Default: celsius",
    )
    parser.add_argument(
        "--wind-unit",
        choices=["kmh", "mph", "ms", "kn"],
        default="kmh",
        help="Wind speed unit. Default: kmh",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Save hourly and daily forecast CSV files under exports/.",
    )
    return parser.parse_args()


def get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    request_url = f"{url}?{urlencode(params)}"
    request = Request(request_url, headers={"User-Agent": "python-pandas-weather-app/1.0"})

    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(body).get("reason", body)
        except json.JSONDecodeError:
            details = body or exc.reason
        raise RuntimeError(f"API request failed: {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach the weather service: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Weather service timed out. Try again in a moment.") from exc


def geocode_location(query: str, country_code: str | None = None) -> list[Location]:
    params: dict[str, Any] = {
        "name": query,
        "count": 5,
        "language": "en",
        "format": "json",
    }
    if country_code:
        params["countryCode"] = country_code.upper()

    payload = get_json(GEOCODING_URL, params)
    locations = []

    for item in payload.get("results", []):
        locations.append(
            Location(
                name=item.get("name", ""),
                country=item.get("country", ""),
                admin1=item.get("admin1", ""),
                latitude=float(item["latitude"]),
                longitude=float(item["longitude"]),
                timezone=item.get("timezone", "auto"),
            )
        )

    return locations


def fetch_forecast(
    location: Location,
    days: int,
    temperature_unit: str,
    wind_unit: str,
) -> dict[str, Any]:
    params = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "timezone": "auto",
        "forecast_days": days,
        "temperature_unit": temperature_unit,
        "wind_speed_unit": wind_unit,
        "current": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "precipitation",
                "weather_code",
                "cloud_cover",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_gusts_10m",
            ]
        ),
        "hourly": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "precipitation_probability",
                "precipitation",
                "weather_code",
                "cloud_cover",
                "wind_speed_10m",
                "wind_direction_10m",
            ]
        ),
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "apparent_temperature_max",
                "apparent_temperature_min",
                "precipitation_sum",
                "precipitation_probability_max",
                "wind_speed_10m_max",
                "wind_gusts_10m_max",
                "sunrise",
                "sunset",
                "uv_index_max",
            ]
        ),
    }
    return get_json(FORECAST_URL, params)


def weather_description(code: Any) -> str:
    if pd.isna(code):
        return "Unknown"
    return WEATHER_CODES.get(int(code), f"Code {int(code)}")


def wind_compass(degrees: Any) -> str:
    if pd.isna(degrees):
        return ""
    directions = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    index = int((float(degrees) + 11.25) / 22.5) % 16
    return directions[index]


def build_frames(forecast: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    hourly = pd.DataFrame(forecast.get("hourly", {}))
    daily = pd.DataFrame(forecast.get("daily", {}))

    if not hourly.empty:
        hourly["time"] = pd.to_datetime(hourly["time"])
        hourly["date"] = hourly["time"].dt.date
        hourly["condition"] = hourly["weather_code"].apply(weather_description)
        hourly["wind_direction"] = hourly["wind_direction_10m"].apply(wind_compass)

    if not daily.empty:
        daily["time"] = pd.to_datetime(daily["time"])
        daily["condition"] = daily["weather_code"].apply(weather_description)
        daily["sunrise"] = pd.to_datetime(daily["sunrise"]).dt.strftime("%H:%M")
        daily["sunset"] = pd.to_datetime(daily["sunset"]).dt.strftime("%H:%M")

    return hourly, daily


def summarize_hourly(hourly: pd.DataFrame) -> pd.DataFrame:
    return (
        hourly.groupby("date", as_index=False)
        .agg(
            avg_temp=("temperature_2m", "mean"),
            feels_like_avg=("apparent_temperature", "mean"),
            rain_total=("precipitation", "sum"),
            max_rain_chance=("precipitation_probability", "max"),
            avg_humidity=("relative_humidity_2m", "mean"),
            max_wind=("wind_speed_10m", "max"),
        )
        .round(1)
    )


def format_value(value: Any, unit: str = "", precision: int = 1) -> str:
    if pd.isna(value):
        return "n/a"
    if isinstance(value, float):
        text = f"{value:.{precision}f}"
    else:
        text = str(value)
    return f"{text} {unit}".strip()


def print_current_weather(location: Location, forecast: dict[str, Any]) -> None:
    current = forecast.get("current", {})
    units = forecast.get("current_units", {})
    code = current.get("weather_code")
    wind_direction = wind_compass(current.get("wind_direction_10m"))

    print(f"\nWeather for {location.display_name}")
    print("-" * (12 + len(location.display_name)))
    print(f"Local time:       {current.get('time', 'n/a')}")
    print(f"Condition:        {weather_description(code)}")
    print(
        "Temperature:      "
        f"{format_value(current.get('temperature_2m'), units.get('temperature_2m', ''))}"
    )
    print(
        "Feels like:       "
        f"{format_value(current.get('apparent_temperature'), units.get('apparent_temperature', ''))}"
    )
    print(
        "Humidity:         "
        f"{format_value(current.get('relative_humidity_2m'), units.get('relative_humidity_2m', ''), 0)}"
    )
    print(
        "Cloud cover:      "
        f"{format_value(current.get('cloud_cover'), units.get('cloud_cover', ''), 0)}"
    )
    print(
        "Precipitation:    "
        f"{format_value(current.get('precipitation'), units.get('precipitation', ''))}"
    )
    print(
        "Wind:             "
        f"{format_value(current.get('wind_speed_10m'), units.get('wind_speed_10m', ''))}"
        f" from {wind_direction}"
    )
    print(
        "Wind gusts:       "
        f"{format_value(current.get('wind_gusts_10m'), units.get('wind_gusts_10m', ''))}"
    )


def print_daily_forecast(daily: pd.DataFrame, forecast: dict[str, Any]) -> None:
    units = forecast.get("daily_units", {})
    display = daily.copy()
    display["date"] = display["time"].dt.strftime("%a %b %d")
    display["temp"] = (
        display["temperature_2m_min"].round(1).astype(str)
        + " to "
        + display["temperature_2m_max"].round(1).astype(str)
        + f" {units.get('temperature_2m_max', '')}"
    )
    display["rain"] = (
        display["precipitation_sum"].round(1).astype(str)
        + f" {units.get('precipitation_sum', '')}"
    )
    display["rain_chance"] = display["precipitation_probability_max"].round(0).astype("Int64").astype(str) + "%"
    display["wind"] = (
        display["wind_speed_10m_max"].round(1).astype(str)
        + f" {units.get('wind_speed_10m_max', '')}"
    )
    display["uv"] = display["uv_index_max"].round(1)

    print("\nDaily forecast")
    print("--------------")
    print(
        display[
            ["date", "condition", "temp", "rain", "rain_chance", "wind", "uv", "sunrise", "sunset"]
        ]
        .rename(
            columns={
                "date": "Date",
                "condition": "Condition",
                "temp": "Temp",
                "rain": "Rain",
                "rain_chance": "Rain %",
                "wind": "Max wind",
                "uv": "UV",
                "sunrise": "Sunrise",
                "sunset": "Sunset",
            }
        )
        .to_string(index=False)
    )


def print_next_24_hours(hourly: pd.DataFrame, forecast: dict[str, Any]) -> None:
    units = forecast.get("hourly_units", {})
    current_time = pd.Timestamp(forecast.get("current", {}).get("time", hourly["time"].min()))
    next_24 = hourly[hourly["time"] >= current_time].head(24).copy()
    if next_24.empty:
        next_24 = hourly.head(24).copy()

    next_24["time"] = next_24["time"].dt.strftime("%a %H:%M")
    next_24["temp"] = (
        next_24["temperature_2m"].round(1).astype(str)
        + f" {units.get('temperature_2m', '')}"
    )
    next_24["rain"] = (
        next_24["precipitation"].round(1).astype(str)
        + f" {units.get('precipitation', '')}"
    )
    next_24["rain_chance"] = next_24["precipitation_probability"].round(0).astype("Int64").astype(str) + "%"
    next_24["wind"] = (
        next_24["wind_speed_10m"].round(1).astype(str)
        + f" {units.get('wind_speed_10m', '')} "
        + next_24["wind_direction"]
    )

    print("\nNext 24 hours")
    print("-------------")
    print(
        next_24[["time", "condition", "temp", "rain_chance", "rain", "wind"]]
        .rename(
            columns={
                "time": "Time",
                "condition": "Condition",
                "temp": "Temp",
                "rain_chance": "Rain %",
                "rain": "Rain",
                "wind": "Wind",
            }
        )
        .to_string(index=False)
    )


def print_pandas_summary(hourly: pd.DataFrame, forecast: dict[str, Any]) -> None:
    units = forecast.get("hourly_units", {})
    summary = summarize_hourly(hourly)
    summary["date"] = pd.to_datetime(summary["date"]).dt.strftime("%a %b %d")
    summary["avg_temp"] = summary["avg_temp"].astype(str) + f" {units.get('temperature_2m', '')}"
    summary["feels_like_avg"] = (
        summary["feels_like_avg"].astype(str) + f" {units.get('apparent_temperature', '')}"
    )
    summary["rain_total"] = summary["rain_total"].astype(str) + f" {units.get('precipitation', '')}"
    summary["max_rain_chance"] = summary["max_rain_chance"].round(0).astype("Int64").astype(str) + "%"
    summary["avg_humidity"] = summary["avg_humidity"].round(0).astype("Int64").astype(str) + "%"
    summary["max_wind"] = summary["max_wind"].astype(str) + f" {units.get('wind_speed_10m', '')}"

    print("\nPandas daily summary from hourly data")
    print("-------------------------------------")
    print(
        summary[
            [
                "date",
                "avg_temp",
                "feels_like_avg",
                "rain_total",
                "max_rain_chance",
                "avg_humidity",
                "max_wind",
            ]
        ]
        .rename(
            columns={
                "date": "Date",
                "avg_temp": "Avg temp",
                "feels_like_avg": "Feels avg",
                "rain_total": "Rain total",
                "max_rain_chance": "Max rain %",
                "avg_humidity": "Avg humid",
                "max_wind": "Max wind",
            }
        )
        .to_string(index=False)
    )


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "weather"


def export_frames(location: Location, hourly: pd.DataFrame, daily: pd.DataFrame) -> list[Path]:
    export_dir = Path("exports")
    export_dir.mkdir(exist_ok=True)
    base_name = slugify(location.display_name)
    hourly_path = export_dir / f"{base_name}-hourly.csv"
    daily_path = export_dir / f"{base_name}-daily.csv"

    hourly.to_csv(hourly_path, index=False)
    daily.to_csv(daily_path, index=False)
    return [hourly_path, daily_path]


def choose_location(matches: list[Location]) -> Location:
    if not matches:
        raise RuntimeError("No matching location found. Try a larger city or add --country-code.")

    if len(matches) > 1:
        print("\nLocation matches:")
        for index, location in enumerate(matches, start=1):
            print(f"  {index}. {location.display_name} ({location.latitude:.2f}, {location.longitude:.2f})")
        print("\nUsing the first match. Add --country-code for a narrower search.")

    return matches[0]


def main() -> int:
    args = parse_args()
    location_query = args.location or input("Enter a city or place name: ").strip()
    if not location_query:
        print("Please provide a location.", file=sys.stderr)
        return 2

    try:
        location = choose_location(geocode_location(location_query, args.country_code))
        forecast = fetch_forecast(
            location,
            days=args.days,
            temperature_unit=args.temperature_unit,
            wind_unit=args.wind_unit,
        )
        hourly, daily = build_frames(forecast)

        if hourly.empty or daily.empty:
            raise RuntimeError("The weather service returned an incomplete forecast.")

        print_current_weather(location, forecast)
        print_daily_forecast(daily, forecast)
        print_next_24_hours(hourly, forecast)
        print_pandas_summary(hourly, forecast)

        if args.export:
            exported = export_frames(location, hourly, daily)
            print("\nExported CSV files:")
            for path in exported:
                print(f"  {path}")

    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
