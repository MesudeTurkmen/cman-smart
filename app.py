from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, auth, firestore, db
from firebase_admin.exceptions import FirebaseError
from dotenv import load_dotenv
import os
import logging
from routes.firebase_crud import *
from routes.weather import *
from routes.auth import *
from geopy import Nominatim
from models.notification import Notification
from models.notification import *
from models.notification import FCMManager
from routes.cafe_recommendation_service import *
import requests
from flask import Blueprint, request
from routes.health import *
import google.generativeai as genai
from bs4 import BeautifulSoup
import requests

# Loglama ve Environment Yapılandırması
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_user(email):
    return db.reference(f'/users/{email}').get()

#konum doğrulama
def validate_location(location: str) -> bool:
    try:
        geolocator = Nominatim(user_agent="weather_app")
        return bool(geolocator.geocode(location))
    except:
        return False
    


# Flask Uygulamasını Başlat
app = Flask(__name__)

# Firebase Başlatma
try:
    # Gerekli environment değişkenlerini kontrol et
    FIREBASE_SERVICE_ACCOUNT = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
    FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL")
    
    if not all([FIREBASE_SERVICE_ACCOUNT, FIREBASE_DB_URL]):
        raise ValueError("Firebase environment değişkenleri eksik")

    # Önceki bağlantıları temizle
    if firebase_admin._apps:
        firebase_admin.delete_app(firebase_admin.get_app())
        logger.info("Önceki Firebase bağlantısı temizlendi")

    # Firebase'i başlat
    cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
    firebase_app = firebase_admin.initialize_app(cred, {
        'databaseURL': FIREBASE_DB_URL
    })
    
    # Servisleri başlat
    firestore_db = firestore.client()
    realtime_db = db.reference('/')
    logger.info("✅ Firebase servisleri başlatıldı")

except (ValueError, FileNotFoundError) as e:
    logger.error(f"❌ Konfigürasyon hatası: {str(e)}")
    firestore_db = None
    realtime_db = None
except FirebaseError as e:
    logger.error(f"❌ Firebase hatası: {str(e)}")
    firestore_db = None
    realtime_db = None
except Exception as e:
    logger.error(f"❌ Kritik hata: {str(e)}", exc_info=True)
    firestore_db = None
    realtime_db = None

def get_location(user_id: str) -> str:
    ref = db.reference(f'users/{user_id}/location')
    location = ref.get()
    
    if location:
        return location
    else:
        return 'Kayseri'


@app.route('/verify-token', methods=['POST'])
def verify_token():
    data = request.get_json()
    id_token = data.get('idToken')

    if not id_token:
        return jsonify({"error": "ID token missing"}), 400

    try:
        # Verify the ID token
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token['uid']
        return jsonify({"message": "Token verified", "uid": uid}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 401

@app.route('/')
def home():
    return "Firebase Auth Flask Backend is running."

@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({"message": "Merhaba AWS!"})

#REGISTER DEVICE
@app.route('/register-device', methods=['POST'])
def register_device():
    try:
        user_id = request.json['user_id']
        token = request.json['token']
        fcm = FCMManager(user_id)
        success = fcm.register_device(token)
        return jsonify({"success": success}), 200 if success else 400
    except KeyError:
        return jsonify({"error": "Geçersiz istek formatı"}), 400
#REGISTER DEVICE

#SET LOCATION 
@app.route('/set_location', methods=['POST'])
def set_location():
    try:
        data = request.get_json()

        user_id = data.get("user_id")
        location = data.get("location")

        if not user_id or not location:
            return jsonify({"error": "Eksik veri"}), 400

        ref = db.reference(f"users/{user_id}/location")
        ref.set(location)

        return jsonify({"message": "Konum başarıyla kaydedildi", "user_id": user_id, "location": location}), 200

    except Exception as e:
        print(f"set_location HATASI: {e}")
        return jsonify({"error": "Sunucu hatası"}), 500
#SET LOCATION

#GEMINI
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-pro')

def analyze_with_gemini(prompt: str, context: str) -> str:
    """Gemini'ye metin analizi yaptırır"""
    try:
        response = model.generate_content(f"{prompt}\n\nContext: {context}")
        return response.text
    except Exception as e:
        logger.error(f"Gemini analiz hatası: {str(e)}")
        return "Durum analizi şu anda mevcut değil"

# --------------------------
# Akıllı Uyarı Sistemleri
# --------------------------
def enhanced_weather_alert(user_id: str, alert_data: dict):
    """Hava durumu uyarılarını Gemini ile zenginleştirir"""
    analysis = analyze_with_gemini(
        prompt="Aşağıdaki hava durumu uyarısını basit Türkçe ile açıkla ve 3 maddelik öneri sun:",
        context=alert_data['message']
    )
    
    enhanced_alert = {
        **alert_data,
        "gemini_analysis": analysis,
        "type": "enhanced_weather_alert"
    }
    
    # Bildirimi kaydet ve gönder
    return send_weather_alert(user_id, enhanced_alert)

def scrape_municipality_announcements(city: str = "ankara") -> list:
    """Belediye duyurularını çeker (Örnek: Ankara Büyükşehir)"""
    try:
        url = f"https://www.{city}.bel.tr/haberler"
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        announcements = []
        for item in soup.select('.news-item'):
            title = item.select_one('.news-title').text.strip()
            date = item.select_one('.news-date').text.strip()
            content = item.select_one('.news-excerpt').text.strip()
            
            announcements.append({
                "title": title,
                "date": date,
                "content": content
            })
            
        return announcements[:5]  # Son 5 duyuru
    
    except Exception as e:
        logger.error(f"Belediye duyuru çekme hatası: {str(e)}")
        return []
#GEMINI END

#WEATHER.PY ENDPOINTS
@app.route('/weather/weekly/<user_id>', methods=['GET'])
def weekly_weather(user_id: str):
    """Kullanıcının konumuna göre 7 günlük hava tahmini"""
    try:
        location = get_location(user_id =user_id)
        api_key = os.getenv("VISUAL_CROSSING_API_KEY")
        
        response = requests.get(
            f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{location}/next7days",
            params={
                "unitGroup": "metric",
                "include": "days",
                "key": api_key,
                "contentType": "json"
            },
            timeout=15
        )
        response.raise_for_status()
        
        weekly_data = []
        for day in response.json().get('days', []):
            weekly_data.append({
                "date": day['datetime'],
                "temp_max": day['tempmax'],
                "temp_min": day['tempmin'],
                "precip_prob": day['precipprob'],
                "conditions": day['conditions'],
                "sunrise": day['sunrise'],
                "sunset": day['sunset']
            })
            
        return jsonify({
            "location": location,
            "forecast_days": len(weekly_data),
            "data": weekly_data
        }), 200
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API hatası: {str(e)}")
        return jsonify({"error": "Hava durumu servisine ulaşılamıyor"}), 503
    except Exception as e:
        logger.error(f"Haftalık tahmin hatası: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/weather/current/<user_id>', methods=['GET'])
def current_weather(user_id: str):
    """Kullanıcının konumuna göre anlık hava durumu"""
    try:
        location = get_location(user_id)
        api_key = os.getenv("VISUAL_CROSSING_API_KEY")
        
        response = requests.get(
            f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{location}/today",
            params={
                "unitGroup": "metric",
                "include": "current",
                "key": api_key,
                "contentType": "json"
            },
            timeout=10
        )
        response.raise_for_status()
        
        current_data = response.json().get('currentConditions', {})
        
        return jsonify({
            "location": location,
            "temp": current_data.get('temp'),
            "feels_like": current_data.get('feelslike'),
            "humidity": current_data.get('humidity'),
            "conditions": current_data.get('conditions')
        }), 200
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Current weather API error: {str(e)}")
        return jsonify({"error": "Hava durumu servisine ulaşılamıyor"}), 503
    except Exception as e:
        logger.error(f"Current weather error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/weather/alerts/<user_id>', methods=['GET'])
def weather_alerts(user_id: str):
    """Kullanıcı için aktif meteorolojik uyarılar"""
    try:
        location = get_location(user_id)
        
        # Gerçek veri için Firebase'den geçmiş veri çek
        ref = db.reference(f'/weather_history/{user_id}')
        historical_data = ref.get()
        
        alerts = check_sudden_change(historical_data, get_weather(location))
        
        return jsonify({
            "location": location,
            "alerts": alerts if alerts else [],
            "last_updated": datetime.now().isoformat()
        }), 200
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Weather alerts API error: {str(e)}")
        return jsonify({"error": "Hava durumu servisine ulaşılamıyor"}), 503
    except Exception as e:
        logger.error(f"Alert processing error: {str(e)}")
        return jsonify({"error": "Uyarılar işlenemedi"}), 500

@app.route('/weather/daily/<user_id>', methods=['GET'])
def daily_detailed_weather(user_id: str):
    """Kullanıcının konumuna göre günün saatlik hava durumu"""
    try:
        # 1. Kullanıcı konumunu al
        location = get_location(user_id)
        
        # 2. API'den saatlik verileri çek
        api_key = os.getenv("VISUAL_CROSSING_API_KEY")
        today = datetime.now().strftime("%Y-%m-%d")
        
        response = requests.get(
            f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{location}/{today}/{today}",
            params={
                "unitGroup": "metric",
                "include": "hours",
                "key": api_key,
                "contentType": "json"
            },
            timeout=15
        )
        response.raise_for_status()
        
        # 3. Veriyi işle
        hourly_data = []
        day_data = response.json().get('days', [{}])[0]
        for hour in day_data.get('hours', []):
            hourly_data.append({
                "time": datetime.fromtimestamp(hour['datetimeEpoch']).strftime("%H:%M"),
                "temp": hour.get('temp'),
                "feels_like": hour.get('feelslike'),
                "humidity": f"%{hour.get('humidity', 0)}",
                "precip_prob": f"%{hour.get('precipprob', 0)}",
                "wind_speed": f"{hour.get('windspeed', 0)} km/s",
                "conditions": hour.get('conditions')
            })
            
        return jsonify({
            "location": location,
            "date": today,
            "hours": hourly_data
        }), 200
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Saatlik veri API hatası: {str(e)}")
        return jsonify({"error": "Hava durumu servisine ulaşılamıyor"}), 503
    except IndexError:
        logger.error("Geçersiz veri yapısı")
        return jsonify({"error": "Servis yanıtı beklenen formatta değil"}), 500
    except Exception as e:
        logger.error(f"Saatlik veri işleme hatası: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

#WEATHER.PY ENDPOINTS END    

#NOTIFICATION.PY ENDPOINT
notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')
# --------------------------
# Temel Bildirim İşlemleri
# --------------------------

@notifications_bp.route('/<user_id>', methods=['POST'])
def create_notification(user_id: str):
    """Yeni bildirim oluşturma"""
    data = request.get_json()
    notifier = Notification(user_id)
    notification_id = notifier.create(
        notification_type=data.get('type', 'general'),
        message=data['message'],
        metadata=data.get('metadata')
    )
    if notification_id:
        return jsonify({"id": notification_id}), 201
    return jsonify({"error": "Bildirim oluşturulamadı"}), 500

@notifications_bp.route('/<user_id>', methods=['GET'])
def get_notifications(user_id: str):
    """Tüm bildirimleri listeleme"""
    notifier = Notification(user_id)
    limit = int(request.args.get('limit', 100))
    return jsonify(notifier.get_all(limit)), 200

@notifications_bp.route('/<user_id>/<notification_id>/read', methods=['PUT'])
def mark_as_read(user_id: str, notification_id: str):
    """Bildirimi okundu olarak işaretleme"""
    notifier = Notification(user_id)
    success = notifier.mark_as_read(notification_id)
    return jsonify({"success": success}), 200 if success else 400

@notifications_bp.route('/<user_id>/<notification_id>', methods=['DELETE'])
def delete_notification(user_id: str, notification_id: str):
    """Bildirimi silme"""
    try:
        ref = db.reference(f'/notifications/{user_id}/{notification_id}')
        ref.delete()
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --------------------------
# Push Bildirim İşlemleri
# --------------------------

@notifications_bp.route('/devices/<user_id>', methods=['POST'])
def register_device(user_id: str):
    """Cihaz token kayıt"""
    data = request.get_json()
    fcm = FCMManager(user_id)
    success = fcm.register_device(data['token'])
    return jsonify({"success": success}), 200 if success else 400

@notifications_bp.route('/push/test/<user_id>', methods=['POST'])
def send_test_push(user_id: str):
    """Test push bildirimi gönderme"""
    fcm = FCMManager(user_id)
    result = fcm.send_push_notification(
        title=request.json.get('title', 'Test Bildirim'),
        body=request.json.get('body', 'Bu bir test bildirimidir'),
        data=request.json.get('data', {'type': 'test'})
    )
    return jsonify(result), 200


@notifications_bp.route('/analyzed-alerts/<user_id>', methods=['GET'])
def get_analyzed_alerts(user_id: str):
    """Zenginleştirilmiş uyarıları getir"""
    ref = db.reference(f'/notifications/{user_id}')
    alerts = ref.order_by_child('type').equal_to('enhanced_weather_alert').get()
    return jsonify(list(alerts.values())), 200

@notifications_bp.route('/municipality-alerts/<user_id>', methods=['POST'])
def trigger_municipality_alert(user_id: str):
    """Belediye duyurularını analiz edip bildirim oluştur"""
    try:
        # 1. Duyuruları çek
        announcements = scrape_municipality_announcements()
        
        # 2. Her duyuruyu analiz et
        for announcement in announcements:
            analysis = analyze_with_gemini(
                prompt="Bu belediye duyurusunu özetle ve vatandaşlar için önemli noktaları listele:",
                context=f"{announcement['title']}\n{announcement['content']}"
            )
            
            # 3. Bildirim oluştur
            Notification(user_id).create(
                notification_type="municipality_alert",
                message=f"Belediye Duyurusu: {announcement['title']}",
                metadata={
                    "original": announcement,
                    "analysis": analysis
                }
            )
            
        return jsonify({"processed_items": len(announcements)}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@notifications_bp.route('/weather-alert/<user_id>', methods=['POST'])
def trigger_weather_alert(user_id: str):
    alert_data = request.get_json()
    return enhanced_weather_alert(user_id, alert_data)
#NOTIFICATION.PY ENDPOINTS END

#HEALTH.PY ENDPOINTS
health_bp = Blueprint('health', __name__, url_prefix='/api/health')
emergency_bp = Blueprint('emergency', __name__, url_prefix='/api/emergency')

@health_bp.route('/<user_id>', methods=['POST'])
def save_health_info(user_id):
    """Kullanıcının sağlık bilgilerini kaydetme"""
    data = request.get_json()
    return save_user_health_data(user_id, data)

@health_bp.route('/<user_id>', methods=['GET'])
def get_health_info(user_id):
    """Kullanıcının sağlık bilgilerini getirme"""
    return get_user_health_data(user_id)

# --------------------------
# Gerçek Zamanlı Sağlık Verileri
# --------------------------

@health_bp.route('/realtime/<user_id>', methods=['GET'])
def realtime_health_data(user_id):
    """Anlık sağlık verilerini getirme"""
    use_real_api = request.args.get('real', 'false').lower() == 'true'
    data = get_realtime_health_data(user_id, use_real_api)
    return jsonify(data), 200

# --------------------------
# Acil Durum Kişi Yönetimi
# --------------------------

@emergency_bp.route('/contacts/<user_id>', methods=['POST'])
def add_contact(user_id):
    """Yeni acil durum kişisi ekleme"""
    contact_data = request.get_json()
    return add_emergency_contact(user_id, contact_data)

@emergency_bp.route('/contacts/<user_id>', methods=['GET'])
def get_contacts(user_id):
    """Acil durum kişilerini listeleme"""
    return get_emergency_contacts(user_id)

@emergency_bp.route('/contacts/<user_id>/<contact_id>', methods=['DELETE'])
def delete_contact(user_id, contact_id):
    """Acil durum kişisini silme"""
    return delete_emergency_contact(user_id, contact_id)

# --------------------------
# Acil Durum Yönetimi
# --------------------------

@emergency_bp.route('/check/<user_id>', methods=['GET'])
def check_emergency_status(user_id):
    """Acil durum kontrolü"""
    is_emergency = check_emergency(user_id)
    return jsonify({"emergency": is_emergency}), 200

@emergency_bp.route('/trigger/<user_id>', methods=['POST'])
def trigger_emergency_action(user_id):
    """Acil durum tetikleme ve SMS gönderme"""
    return trigger_emergency(user_id)
#HEALTH.PY ENDPOINTS END

#CAFE RECOMMENDATION SERVICE ENDPOINTS
@app.route("/cafes/nearest", methods=["GET"])
def get_nearest_cafes():
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    
    if not lat or not lon:
        return jsonify({"error": "Latitude ve longitude gereklidir."}), 400

    try:
        result = CafeRecommendationService.find_nearest_cafes(lat, lon)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route("/cafes/distance", methods=["GET"])
def get_distance():
    try:
        lat1 = float(request.args.get("lat1"))
        lon1 = float(request.args.get("lon1"))
        lat2 = float(request.args.get("lat2"))
        lon2 = float(request.args.get("lon2"))
    except (TypeError, ValueError):
        return jsonify({"error": "Tüm koordinatlar sayısal olmalı."}), 400

    distance = CafeRecommendationService.calculate_distance(lat1, lon1, lat2, lon2)
    return jsonify({"distance_meters": round(distance, 2)}), 200

@app.route("/cafes/top5", methods=["GET"])
def get_top5_cafes():
    lat = request.args.get("lat") #39.96939957261083
    lon = request.args.get("lon") #32.744049317303556

    if not lat or not lon:
        return jsonify({"error": "Lat ve lon zorunlu"}), 400

    try:
        result = CafeRecommendationService.find_top5_cafes(lat, lon)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
#CAFE RECOMMENDATION SERVICE ENDPOINTS END 



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)