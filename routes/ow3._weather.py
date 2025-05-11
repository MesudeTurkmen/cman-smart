# routes/weather.py
import requests
from flask import jsonify, request
import os
import logging
from dotenv import load_dotenv
from datetime import datetime, timedelta
from functools import lru_cache
from firebase_admin import db

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Helper Functions
@lru_cache(maxsize=50)  # Koordinatları önbelleğe al
def get_city_coordinates(city: str) -> tuple:
    geo_url = "http://api.openweathermap.org/geo/1.0/direct"
    params = {
        'q': city,
        'limit': 1,
        'appid': os.getenv("OPENWEATHER_API_KEY")
    }
    
    try:
        response = requests.get(geo_url, params=params, timeout=10)
        response.raise_for_status()  # HTTP hatalarını yakala
        
        data = response.json()
        if not data:
            raise ValueError("Şehir bulunamadı")
            
        return (data[0]['lat'], data[0]['lon'])
    
    except (requests.exceptions.RequestException, KeyError, ValueError) as e:
        raise RuntimeError(f"Koordinat alınamadı: {str(e)}")

def validate_weather_data(data: dict) -> bool:
    required_keys = {'current', 'hourly', 'daily'}
    return all(key in data for key in required_keys)


def get_weather(city: str) -> tuple:
    """
    Gelişmiş hava durumu tahmini (48 saatlik + 7 günlük).
    
    Args:
        city (str): Şehir adı
    
    Returns:
        tuple: (JSON response, HTTP status code)
    """
    try:
        # 1. Koordinatları al (Önbellek kullanır)
        lat, lon = get_city_coordinates(city)
        
        # 2. Hava durumu verisini çek
        weather_url = "https://api.openweathermap.org/data/3.0/onecall"
        params = {
            'lat': lat,
            'lon': lon,
            'exclude': 'minutely,alerts',
            'units': 'metric',
            'lang': 'tr',
            'appid': os.getenv("OPENWEATHER_API_KEY")
        }
        
        response = requests.get(weather_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # 3. Veri yapısını doğrula
        if not validate_weather_data(data):
            raise ValueError("Geçersiz API yanıtı")
        
        # 4. Detaylı veri işleme
        processed_data = {
            "metadata": {
                "city": city,
                "lat": lat,
                "lon": lon,
                "timezone": data.get('timezone', 'UTC')
            },
            "current": process_current_data(data['current']),
            "hourly": process_hourly_data(data['hourly']),
            "daily": process_daily_data(data['daily'])
        }
        
        return jsonify(processed_data), 200
    
    except requests.exceptions.Timeout:
        return jsonify({"error": "API zaman aşımı"}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"API hatası: {str(e)}"}), 502
    except (ValueError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Beklenmeyen hata: {str(e)}"}), 500


#data processing functions
def process_current_data(current: dict) -> dict:
    """Anlık veriyi işler."""
    return {
        "temp": current.get('temp', 'N/A'),
        "feels_like": current.get('feels_like', 'N/A'),
        "humidity": f"%{current.get('humidity', 0)}",
        "wind": {
            "speed": f"{current.get('wind_speed', 0)} m/s",
            "deg": current.get('wind_deg', 'N/A'),
            "gust": f"{current.get('wind_gust', 0)} m/s"
        },
        "uvi": current.get('uvi', 'N/A'),
        "clouds": f"%{current.get('clouds', 0)}",
        "weather": current['weather'][0]['description'] if current.get('weather') else 'N/A'
    }

def process_hourly_data(hourly: list) -> list:
    """Saatlik veriyi işler."""
    processed = []
    for hour in hourly[:24]:  # 24 saatlik veri
        processed.append({
            "time": datetime.fromtimestamp(hour['dt']).strftime("%H:%M"),
            "temp": hour.get('temp', 'N/A'),
            "pop": f"%{int(hour.get('pop', 0)*100)}",
            "rain": hour.get('rain', {}).get('1h', 0),
            "uvi": hour.get('uvi', 'N/A'),
            "weather": hour['weather'][0]['description'] if hour.get('weather') else 'N/A'
        })
    return processed

def process_daily_data(daily: list) -> list:
    """Günlük veriyi işler."""
    processed = []
    for day in daily[:5]:  # 5 günlük veri
        processed.append({
            "date": datetime.fromtimestamp(day['dt']).strftime("%d.%m"),
            "temp": {
                "min": day['temp'].get('min', 'N/A'),
                "max": day['temp'].get('max', 'N/A')
            },
            "uvi": day.get('uvi', 'N/A'),
            "rain": day.get('rain', 0),
            "summary": day['weather'][0]['description'] if day.get('weather') else 'N/A'
        })
    return processed

@lru_cache(maxsize=100)  # Sık erişilen kullanıcı verilerini önbelleğe al
def get_time(user_id: str) -> str:
    """Firebase'den kullanıcının bildirim saatini çeker."""
    try:
        return db.reference(f'/users/{user_id}/notification_time').get() or "08:00"
    except Exception:
        return "08:00"
    
#def check_sudden_change(user_id: str, city: str) -> bool:
    """
    Basitleştirilmiş Anomali Tespiti:
    1. Sadece kritik sıcaklık değişimini kontrol eder
    2. Firebase'e direkt kayıt yapar
    3. Önbellek kullanmaz (gerçek zamanlı veriyle çalışır)
    """
    try:
        # 1. Anlık hava durumu verisini al
        current_data = get_current_weather_data(city)
        if not current_data:
            return False

        # 2. Basit anomali kontrolü (örnek: 10°C'den fazla değişim)
        temp_change = abs(current_data['temp'] - current_data.get('feels_like', current_data['temp']))
        if temp_change < 10:
            return False

        # 3. Gemini ile mesaj oluştur (başka dosyadan çağır)
        message = generate_alert_message(
            city=city,
            temp_change=temp_change,
            threshold=10
        )

        # 4. Firebase'e kaydet
        alert_ref = db.reference(f'/users/{user_id}/weather_alerts')
        alert_ref.push().set({
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "temp_change": temp_change
        })
        
        return True

    except Exception as e:
        logger.error(f"Anomali tespit hatası: {str(e)}")
        return False

#def get_current_weather_data(city: str) -> dict:
    """Basit hava durumu verisi çeker (önbelleksiz)"""
    try:
        response = requests.get(
            f"http://api.openweathermap.org/data/2.5/weather?q={city}&units=metric&appid={os.getenv('OPENWEATHER_API_KEY')}",
            timeout=10
        )
        return response.json().get('main', {})
    except Exception as e:
        logger.error(f"Hava durumu alınamadı: {str(e)}")
        return {}
    
#print("✅ Weather modülü başarıyla yüklendi!")
# Test kodu
#print(get_weather("Istanbul"))
#print(get_weather("Ankara"))
