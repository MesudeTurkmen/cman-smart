from firebase_admin import auth
from firebase_admin import db

# Kullanıcı kayıt fonksiyonu
def create_user(email: str, password: str, location: str):
    try:
        # 1. Kullanıcı oluştur
        user = auth.create_user(
            email=email,
            password=password
        )
        
        # 2. Realtime DB'ye kullanıcı verisini yaz
        ref = db.reference(f'/users/{user.uid}')
        ref.set({
            'email': email,
            'location': location,
            'notification_time': '08:00'
        })
        return user.uid
        
    except auth.EmailAlreadyExistsError:
        raise Exception("Bu e-posta zaten kayıtlı")