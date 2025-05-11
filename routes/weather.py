import requests
from flask import jsonify, request
import os
import logging
from dotenv import load_dotenv
from datetime import datetime, timedelta
from functools import lru_cache
from firebase_admin import db
from typing import Dict, Optional
from models.notification import send_weather_alert
from models.notification import Notification

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEMP_DROP_THRESHOLD = 5  # °C cinsinden sıcaklık düşüşü eşiği

def get_weather(city: str) -> dict:
    """Visual Crossing API ile hava durumu ve yağış bilgisini çeker."""
    api_key = os.getenv("VISUAL_CROSSING_API_KEY")
    base_url = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/"
    
    try:
        # API isteği (precip ve precipcover parametreleri eklendi)
        response = requests.get(
            f"{base_url}{city}/today"
            f"?unitGroup=metric"
            f"&include=hours%2Ccurrent%2Cprecip%2Cprecipcover"
            f"&key={api_key}"
            f"&contentType=json",
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        # Anlık verileri işle
        current = data.get('currentConditions', {})
        
        # Saatlik verileri işle
        hourly = []
        for hour in data.get('days', [{}])[0].get('hours', []):
            hourly.append({
                "time": datetime.fromtimestamp(hour['datetimeEpoch']).strftime("%H:%M"),
                "temp": hour.get('temp'),
                "precip": hour.get('precip', 0),  # mm cinsinden
                "precip_prob": f"%{int(hour.get('precipprob', 0))}",  # Yağış olasılığı
                "precip_type": hour.get('preciptype', 'Yok')  # Yağış türü (yağmur/kar)
            })
        
        return {
            "city": city,
            "current": {
                "temp": current.get('temp'),
                "feels_like": current.get('feelslike'),
                "humidity": f"%{current.get('humidity', 0)}",
                "wind_speed": f"{current.get('windspeed', 0)} km/s",
                "precip": current.get('precip', 0),
                "precip_type": current.get('preciptype', 'Yok')
            },
            "hourly": hourly
        }
    
    except requests.exceptions.RequestException as e:
        logger.error(f"API hatası: {str(e)}")
        return None
    except KeyError as e:
        logger.error(f"Geçersiz veri yapısı: {str(e)}")
        return None
    
@lru_cache(maxsize=100)  # Sık erişilen kullanıcı verilerini önbelleğe al
def get_time(user_id: str) -> str:
    """Firebase'den kullanıcının bildirim saatini çeker."""
    try:
        return db.reference(f'/users/{user_id}/notification_time').get() or "08:00"
    except Exception:
        return "08:00"
    
print(get_weather("Ankara"))
print(get_time("user123"))

def check_sudden_change(user_id: str, previous_data: Dict, current_data: Dict) -> Optional[Dict]:
    alerts = []
    
    # Sıcaklık düşüş kontrolü
    temp_diff = previous_data['current']['temp'] - current_data['current']['temp']
    if temp_diff >= TEMP_DROP_THRESHOLD:
        alert = {
            "type": "temperature_drop",
            "message": f"Sıcaklık son 1 saatte {temp_diff}°C düştü!",
            "location": current_data['location']
        }
        alerts.append(alert)
        send_weather_alert(user_id, alert)  # 🔔 Bildirim tetikleme