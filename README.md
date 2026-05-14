# Python Pandas Weather App

A terminal weather app that searches for a location, fetches live forecast data from Open-Meteo, and uses pandas to shape the hourly and daily forecast tables.

## Features

- City search with optional country filtering
- Current weather snapshot
- 7-day forecast by default, configurable up to 16 days
- Next 24 hours table
- pandas daily summary calculated from hourly forecast data
- Optional CSV export for the hourly and daily DataFrames
- No API key required

## Setup

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python.exe weather_app.py "Warsaw"
```

Use Fahrenheit and miles per hour:

```powershell
.\.venv\Scripts\python.exe weather_app.py "New York" --country-code US --temperature-unit fahrenheit --wind-unit mph
```

Export the pandas DataFrames as CSV files:

```powershell
.\.venv\Scripts\python.exe weather_app.py "Tokyo" --days 10 --export
```
