import random
from datetime import datetime
from firebase_admin import db
from flask import jsonify, request
import requests
import os
from dotenv import load_dotenv

load_dotenv()

def save_user_health_data(user_id, data):
    """Kullanıcının boy, kilo, kan grubu gibi bilgilerini Firebase'e kaydeder."""
    try:
        ref = db.reference(f'/users/{user_id}/health_info')
        ref.set({
            "blood_type": data.get('blood_type', 'Unknown'),
            "height": data.get('height', 0),     # cm cinsinden (default: 0)
            "weight": data.get('weight', 0),     # kg cinsinden (default: 0)
            "allergies": data.get('allergies', [])
        })
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_user_health_data(user_id):
    try:
        ref = db.reference(f'/users/{user_id}/health_info')
        data = ref.get() or {}
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def generate_synthetic_health_data():
    return {
        "heart_rate": random.randint(60, 100),   # Kalp atışı (bpm)
        "steps": random.randint(0, 10000),       # Adım sayısı
        "sleep_duration": round(random.uniform(4.0, 8.0)),  # Uyku süresi (saat)
        "timestamp": datetime.now().isoformat()
    }


def get_fitbit_data(user_id):
    """Fitbit API'den gerçek veri çeker (OAuth 2.0 gerektirir)."""
    access_token = os.getenv("FITBIT_ACCESS_TOKEN")
    if not access_token:
        return None
    
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(
            "https://api.fitbit.com/1/user/-/activities/heart/date/today/1d.json",
            headers=headers
        )
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print("Fitbit API Hatası:", str(e))
        return None

def get_realtime_health_data(user_id, use_real_api=False):
    if use_real_api:
        return get_fitbit_data(user_id) or generate_synthetic_health_data()
    else:
        return generate_synthetic_health_data()


def check_emergency(user_id):
    health_data = get_realtime_health_data(user_id)
    
    # Örnek Acil Durum Koşulları
    emergency = False
    if health_data["heart_rate"] < 50 or health_data["heart_rate"] > 120:
        emergency = True
    elif health_data["steps"] == 0 and health_data["sleep_duration"] > 12:
        emergency = True
    
    if emergency:
        # Firebase'e acil durum kaydet veya 112'yi ara
        db.reference(f'/emergency_alerts/{user_id}').push().set({
            "message": "Acil durum tespit edildi!",
            "data": health_data,
            "timestamp": datetime.now().isoformat()
        })
        return True
    return False

def add_emergency_contact(user_id, contact_data):
    """
    Yeni acil durum kişisi ekler veya günceller.
    """
    try:
        ref = db.reference(f'/users/{user_id}/emergency_contacts')
        # Otomatik ID oluştur ve veriyi kaydet
        new_contact_ref = ref.push()
        new_contact_ref.set({
            "name": contact_data.get('name'),
            "phone": contact_data.get('phone'),
            "relationship": contact_data.get('relationship')
        })
        return jsonify({"success": True, "contact_id": new_contact_ref.key}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
def get_emergency_contacts(user_id):
    """
    Kullanıcının tüm acil durum kişilerini listeler.
    """
    try:
        ref = db.reference(f'/users/{user_id}/emergency_contacts')
        contacts = ref.get() or {}
        return jsonify(contacts), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
def delete_emergency_contact(user_id, contact_id):
    """
    Belirli bir acil durum kişisini siler.
    """
    try:
        ref = db.reference(f'/users/{user_id}/emergency_contacts/{contact_id}')
        ref.delete()
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
from routes.health import *
from twilio.rest import Client
import os

def send_emergency_sms(user_id, message):
    """
    Acil durum kişilerine SMS gönderir.
    """
    try:
        # Acil durum kişilerini al
        contacts = get_emergency_contacts(user_id).get_json()
        
        # Twilio client'ı başlat
        client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
        
        # Her bir kişiye SMS gönder
        for contact_id, contact in contacts.items():
            client.messages.create(
                body=f"ACİL DURUM: {message}",
                from_=os.getenv("TWILIO_PHONE_NUMBER"),
                to=contact['phone']
            )
        return True
    except Exception as e:
        print("SMS gönderilemedi:", str(e))
        return False

def trigger_emergency(user_id):
    """
    Acil durum tespit edildiğinde çalışır.
    """
    emergency_detected = check_emergency(user_id)  # Önceki check_emergency fonksiyonu
    if emergency_detected:
        success = send_emergency_sms(user_id, "Kullanıcı acil durumda! Lütfen iletişime geçin.")
        return jsonify({"success": success}), 200
    return jsonify({"message": "Acil durum yok"}), 200