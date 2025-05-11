from firebase_admin import messaging
from firebase_admin.exceptions import FirebaseError
from firebase_admin import db
from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class Notification:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.ref = db.reference(f'/notifications/{user_id}')

    def create(self, notification_type: str, message: str, metadata: dict = None) -> str:
        """Yeni bildirim oluştur ve Firebase'e kaydet"""
        try:
            new_notification = {
                "type": notification_type,
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "read": False,
                "metadata": metadata or {}
            }
            return self.ref.push(new_notification).key
        except Exception as e:
            logger.error(f"Bildirim oluşturma hatası: {str(e)}")
            return None

    def mark_as_read(self, notification_id: str) -> bool:
        """Bildirimi okundu olarak işaretle"""
        try:
            self.ref.child(notification_id).update({"read": True})
            return True
        except Exception as e:
            logger.error(f"Okunma durumu güncelleme hatası: {str(e)}")
            return False

    def get_all(self, limit: int = 100) -> list:
        """Kullanıcının tüm bildirimlerini getir"""
        try:
            return list(self.ref.order_by_child('timestamp').limit_to_last(limit).get().values())
        except Exception as e:
            logger.error(f"Bildirim çekme hatası: {str(e)}")
            return []

class FCMManager:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.devices_ref = db.reference(f'/devices/{user_id}')

    def register_device(self, token: str) -> bool:
        """Yeni cihaz token'ını kaydet"""
        try:
            self.devices_ref.push().set({
                'token': token,
                'platform': 'android',  # veya ios/web
                'created_at': datetime.now().isoformat()
            })
            return True
        except Exception as e:
            logger.error(f"Cihaz kayıt hatası: {str(e)}")
            return False

    def send_push_notification(self, title: str, body: str, data: dict = None) -> dict:
        """FCM üzerinden push bildirim gönder"""
        try:
            devices = self.devices_ref.get()
            tokens = [device['token'] for device in devices.values() if 'token' in device]

            if not tokens:
                return {'success': 0, 'failure': 0}

            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                data=data or {},
                tokens=tokens
            )

            response = messaging.send_multicast(message)
            return {'success': response.success_count, 'failure': response.failure_count}
        except FirebaseError as e:
            logger.error(f"FCM hatası: {str(e)}")
            return {'error': str(e)}
        except Exception as e:
            logger.error(f"Genel bildirim hatası: {str(e)}")
            return {'error': 'Internal server error'}

def send_weather_alert(user_id: str, alert_data: Dict):
    """Hem DB'ye kaydet hem push gönder"""
    try:
        notifier = Notification(user_id)
        notification_id = notifier.create(
            notification_type="weather_alert",
            message=alert_data['message'],
            metadata=alert_data
        )

        fcm = FCMManager(user_id)
        push_result = fcm.send_push_notification(
            title="⛈️ Hava Durumu Uyarısı",
            body=alert_data['message'],
            data={
                'type': 'weather_alert',
                'notification_id': notification_id,
                'deep_link': f"app://weather/alerts/{alert_data['alert_id']}"
            }
        )

        logger.info(f"Push gönderim sonucu: {push_result}")
        return notification_id
    except Exception as e:
        logger.error(f"Bildirim gönderim hatası: {str(e)}")
        return None