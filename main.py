"""
Kisan AI backend, offline version (no external APIs).

All data is local. Weather and mandi prices are DEMO data, not live values.

Endpoints:
  GET  /                    health check
  GET  /api/cities          list cities with demo weather
  GET  /api/weather?city=   demo current weather + 3-day forecast
  GET  /api/mandi?q=        search sample mandi prices
  POST /api/chat            rule-based farming assistant reply
  POST /api/crop-photo      validate an uploaded crop photo

Run:
  uvicorn main:app --reload
Docs:
  http://127.0.0.1:8000/docs
"""

import os
import re
from datetime import date, timedelta
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]

MAX_PHOTO_BYTES = 10 * 1024 * 1024
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}

Lang = Literal["en", "hi", "hinglish"]

app = FastAPI(title="Kisan AI API (offline)", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Local demo data
# ---------------------------------------------------------------------------
# Typical-ish baseline values per city. Not measured or live.
CITIES = {
    "ranchi":    {"name": "Ranchi",    "country": "India", "latitude": 23.34, "longitude": 85.31, "temp": 27, "humidity": 62, "wind": 11},
    "lucknow":   {"name": "Lucknow",   "country": "India", "latitude": 26.85, "longitude": 80.95, "temp": 29, "humidity": 55, "wind": 9},
    "agra":      {"name": "Agra",      "country": "India", "latitude": 27.18, "longitude": 78.02, "temp": 30, "humidity": 48, "wind": 10},
    "patna":     {"name": "Patna",     "country": "India", "latitude": 25.60, "longitude": 85.14, "temp": 28, "humidity": 70, "wind": 8},
    "jaipur":    {"name": "Jaipur",    "country": "India", "latitude": 26.91, "longitude": 75.79, "temp": 31, "humidity": 40, "wind": 13},
    "pune":      {"name": "Pune",      "country": "India", "latitude": 18.52, "longitude": 73.86, "temp": 28, "humidity": 58, "wind": 12},
    "bhopal":    {"name": "Bhopal",    "country": "India", "latitude": 23.26, "longitude": 77.41, "temp": 29, "humidity": 52, "wind": 9},
    "nagpur":    {"name": "Nagpur",    "country": "India", "latitude": 21.15, "longitude": 79.09, "temp": 31, "humidity": 50, "wind": 10},
}

# Pattern of weather codes (WMO-style) and temperature swings, cycled by day.
FORECAST_CODES = [1, 2, 3, 61, 0, 2, 80]
FORECAST_SWINGS = [0, 1, -1, 2, 0, -2, 1]

# Sample mandi prices. Not live market rates.
SAMPLE_MANDI = [
    {"crop": "Rice", "market": "Ranchi", "price": 2200},
    {"crop": "Wheat", "market": "Lucknow", "price": 2450},
    {"crop": "Maize", "market": "Ranchi", "price": 1950},
    {"crop": "Potato", "market": "Agra", "price": 1200},
    {"crop": "Tomato", "market": "Patna", "price": 1800},
    {"crop": "Mustard", "market": "Jaipur", "price": 5600},
    {"crop": "Rice", "market": "Patna", "price": 2150},
    {"crop": "Wheat", "market": "Ranchi", "price": 2400},
]


# ---------------------------------------------------------------------------
# Rule-based chatbot
# ---------------------------------------------------------------------------
BOT_RULES = [
    (r"hello|hi\b|namaste|नमस्ते|हेलो|प्रणाम", "botGreeting"),
    (r"water|irrigat|paani|पानी|सिंचाई", "botWater"),
    (r"soil|mitti|मिट्टी|जमीन", "botSoil"),
    (r"disease|bimari|बीमारी|रोग|patta|पत्ता", "botDisease"),
    (r"fertili[sz]er|khaad|खाद|उर्वरक", "botFertilizer"),
    (r"scheme|yojana|योजना|सरकारी", "botScheme"),
    (r"weather|mausam|मौसम|बारिश|rain", "botWeather"),
    (r"mandi|price|bhav|भाव|बाजार|market", "botMarket"),
]

BOT_REPLIES = {
    "en": {
        "botGreeting": "Namaste! How can I help you with farming today?",
        "botWater": "Irrigation depends on the crop, soil moisture and weather. Check soil moisture and follow local agricultural advice.",
        "botSoil": "A soil test helps identify nutrient levels and pH. Ask your local agricultural office about soil testing.",
        "botDisease": "A text message cannot confirm plant disease. Have a clear crop photo reviewed by an agricultural expert.",
        "botFertilizer": "Choose fertilizer based on a soil test and the crop's needs. Avoid guessing fertilizer doses.",
        "botScheme": "Check official scheme information at pmkisan.gov.in or pmfby.gov.in. Eligibility and rules may change.",
        "botWeather": "Use the Weather section above to check the forecast for your city.",
        "botMarket": "The mandi table contains sample prices, not live rates. Check Agmarknet for current market information.",
        "botFallback": "I can answer some general farming questions. For crop-specific treatment, please consult an agricultural expert.",
    },
    "hi": {
        "botGreeting": "नमस्ते! आज खेती में मैं आपकी कैसे मदद कर सकता हूँ?",
        "botWater": "सिंचाई फसल, मिट्टी की नमी और मौसम पर निर्भर करती है। मिट्टी की नमी जाँचें और स्थानीय कृषि सलाह अपनाएँ।",
        "botSoil": "मिट्टी की जाँच से पोषक तत्वों और pH की जानकारी मिल सकती है। स्थानीय कृषि कार्यालय से संपर्क करें।",
        "botDisease": "सिर्फ संदेश से पौधों की बीमारी की पुष्टि नहीं की जा सकती। फोटो कृषि विशेषज्ञ को दिखाएँ।",
        "botFertilizer": "मिट्टी की जाँच और फसल की जरूरत के अनुसार उर्वरक चुनें। मात्रा का अनुमान न लगाएँ।",
        "botScheme": "आधिकारिक जानकारी के लिए pmkisan.gov.in या pmfby.gov.in देखें। पात्रता और नियम बदल सकते हैं।",
        "botWeather": "अपने शहर का पूर्वानुमान देखने के लिए ऊपर मौसम वाले सेक्शन का उपयोग करें।",
        "botMarket": "मंडी तालिका में नमूना भाव हैं, लाइव भाव नहीं। वर्तमान जानकारी के लिए Agmarknet देखें।",
        "botFallback": "मैं खेती की कुछ सामान्य जानकारी दे सकता हूँ। फसल के इलाज के लिए कृषि विशेषज्ञ से सलाह लें।",
    },
    "hinglish": {
        "botGreeting": "Namaste! Aaj farming mein main aapki kya help kar sakta hoon?",
        "botWater": "Irrigation crop, soil moisture aur weather par depend karti hai. Soil moisture check karein aur local advice follow karein.",
        "botSoil": "Soil test se nutrients aur pH ki jaankari mil sakti hai. Local agriculture office se contact karein.",
        "botDisease": "Sirf message se plant disease confirm nahi ho sakti. Photo agriculture expert ko dikhayein.",
        "botFertilizer": "Fertilizer soil test aur crop requirement ke hisaab se choose karein. Dose guess na karein.",
        "botScheme": "Official details ke liye pmkisan.gov.in ya pmfby.gov.in check karein.",
        "botWeather": "City ka forecast dekhne ke liye upar Weather section use karein.",
        "botMarket": "Mandi table mein sample prices hain, live rates nahi. Agmarknet check karein.",
        "botFallback": "Main general farming information de sakta hoon. Crop treatment ke liye agriculture expert se salah lein.",
    },
}


def pick_reply_key(message: str) -> str:
    text = message.lower()
    for pattern, key in BOT_RULES:
        if re.search(pattern, text):
            return key
    return "botFallback"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    language: Lang = "en"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
def health():
    return {"status": "ok", "service": "Kisan AI API (offline)", "demo_data": True}


@app.get("/api/cities")
def list_cities():
    return {"cities": [city["name"] for city in CITIES.values()], "demo": True}


@app.get("/api/weather")
def get_weather(city: str = Query(..., min_length=1, max_length=100)):
    """Returns demo weather in the same shape the frontend's renderWeather() uses."""
    entry = CITIES.get(city.strip().lower())
    if entry is None:
        raise HTTPException(status_code=404, detail="City not found in demo data")

    today = date.today()
    days = [today + timedelta(days=i) for i in range(3)]
    daily = {
        "time": [d.isoformat() for d in days],
        "temperature_2m_max": [],
        "temperature_2m_min": [],
        "weather_code": [],
    }
    for i in range(3):
        swing = FORECAST_SWINGS[(today.toordinal() + i) % len(FORECAST_SWINGS)]
        daily["temperature_2m_max"].append(entry["temp"] + 3 + swing)
        daily["temperature_2m_min"].append(entry["temp"] - 5 + swing)
        daily["weather_code"].append(FORECAST_CODES[(today.toordinal() + i) % len(FORECAST_CODES)])

    return {
        "demo": True,
        "place": {
            "name": entry["name"],
            "country": entry["country"],
            "latitude": entry["latitude"],
            "longitude": entry["longitude"],
        },
        "current": {
            "temperature_2m": entry["temp"],
            "relative_humidity_2m": entry["humidity"],
            "wind_speed_10m": entry["wind"],
            "weather_code": daily["weather_code"][0],
        },
        "daily": daily,
    }


@app.get("/api/mandi")
def get_mandi(q: str = Query("", max_length=100)):
    query = q.strip().lower()
    matches = [
        {**item, "data_type": "demo"}
        for item in SAMPLE_MANDI
        if query in f"{item['crop']} {item['market']}".lower()
    ]
    return {"demo": True, "count": len(matches), "items": matches}


@app.post("/api/chat")
def chat(payload: ChatRequest):
    key = pick_reply_key(payload.message)
    return {"reply": BOT_REPLIES[payload.language][key], "rule_based": True}


@app.post("/api/crop-photo")
async def check_crop_photo(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_PHOTO_TYPES:
        raise HTTPException(status_code=415, detail="Use a JPG, PNG or WEBP image")

    contents = await file.read(MAX_PHOTO_BYTES + 1)
    if len(contents) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Image must be smaller than 10 MB")

    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": len(contents),
        "diagnosis": None,
        "message": "Photo received. AI disease diagnosis is not connected yet.",
    }
