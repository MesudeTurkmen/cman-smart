import requests
from math import radians, cos, sin, sqrt, atan2
import os 
from dotenv import load_dotenv

load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

class CafeRecommendationService: 

    PRIORITY_CAFE_IDS = {
        # Örnek: place_id’ler
        "ChIJN1t_tDeuEmsRUsoyG83frY4",  # Cafe A
        "ChIJsZ3vcCyuEmsRKW5sQ2W-CRg",  # Cafe B
    }

    @staticmethod
    def find_top5_cafes(lat: float, lon: float) -> list:
        """Güncellenmiş parametre kullanımı"""
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        params = {
            "location": f"{lat},{lon}",  # Doğrudan float değerleri kullan
            "radius": 2000,
            "type": "cafe",
            "key": GOOGLE_MAPS_API_KEY
        }

        response = requests.get(url, params=params)
        data = response.json()

        if "results" not in data or not data["results"]:
            return {"error": "Kafe bulunamadı"}

        # Filtrelenmiş kafe listesi + mesafe hesaplama
        cafes_with_distance = []
        for cafe in data["results"]:
            place_id = cafe.get("place_id")
            name = cafe.get("name", "")
            if "cafe" in cafe.get("types", []) and any(k in name.lower() for k in ["cafe", "coffee", "kafe"]):
                loc = cafe["geometry"]["location"]
                distance = CafeRecommendationService.calculate_distance(
                    latitude, longitude, loc["lat"], loc["lng"]
                )
                cafes_with_distance.append((cafe, distance))

        # Öncelikli kafeleri öne al
        priority_cafes = []
        other_cafes = []

        seen_ids = set()
        for cafe, dist in cafes_with_distance:
            place_id = cafe["place_id"]
            if place_id in CafeRecommendationService.PRIORITY_CAFE_IDS:
                priority_cafes.append((cafe, dist))
                seen_ids.add(place_id)
            else:
                other_cafes.append((cafe, dist))

        # Diğerlerini mesafeye göre sırala
        other_cafes = sorted(other_cafes, key=lambda x: x[1])

        # Listeyi birleştir
        combined = priority_cafes + [c for c in other_cafes if c[0]["place_id"] not in seen_ids]
        top_5 = combined[:5]

        # Çıktıyı hazırla
        results = []
        for cafe, distance in top_5:
            results.append({
                "name": cafe["name"],
                "address": cafe.get("vicinity", "Adres yok"),
                "distance_meters": round(distance, 2),
                "google_maps_link": f"https://www.google.com/maps/place/?q=place_id:{cafe['place_id']}",
                "priority": cafe["place_id"] in CafeRecommendationService.PRIORITY_CAFE_IDS
            })

        return results

    @staticmethod
    def calculate_distance(lat1, lon1, lat2, lon2):
        """
        Calculate the distance between two points (lat1, lon1) and (lat2, lon2) in meters.
        """
        R = 6371000  # Radius of the Earth in meters
        # Düzeltildi: Koordinatlar radyan cinsine dönüştürülüyor
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c

    @staticmethod
    def find_nearest_cafes(latitude: float, longitude: float):
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except ValueError:
            return {"error": "Geçersiz koordinat değerleri. Lütfen sayısal değerler girin."}
        
        """Parametreler artık direkt float olarak alınıyor"""
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        params = {
            "location": f"{latitude},{longitude}",  # Float direkt kullanım
            "radius": 2000,
            "type": "cafe",
            "key": GOOGLE_MAPS_API_KEY
        }

        response = requests.get(url, params=params)
        if response.status_code != 200:
            return {"error": "API isteği başarısız oldu", "details": response.text}
        data = response.json()
        if not data.get("results"):
            return {"error": "Yakında kafe bulunamadı", "details": data}
        # Filtreleme: Adında veya türünde "kafe", "cafe", "coffee" geçen yerleri seç
        filtered_cafes = [
            cafe for cafe in data["results"]
            if "cafe" in cafe.get("types", []) and
            any(keyword in cafe.get("name", "").lower() for keyword in ["kafe", "cafe", "coffee"])
        ]

        if not filtered_cafes:
            return {"error": "Adında veya türünde 'kafe', 'cafe', 'coffee' geçen uygun bir yer bulunamadı"}

        # Mesafeleri hesapla ve listele
        cafes_with_distances = []
        for cafe in filtered_cafes:
            cafe_location = cafe.get("geometry", {}).get("location", {})
            if not cafe_location:
                continue  # Eğer konum bilgisi eksikse atla

            # Mesafeyi hesapla
            distance = CafeRecommendationService.calculate_distance(
                float(latitude), float(longitude),
                cafe_location.get("lat", 0), cafe_location.get("lng", 0)
            )

            # Mesafeyi ve kafe bilgilerini listeye ekle
            cafes_with_distances.append((cafe, distance))

        if not cafes_with_distances:
            return {"error": "2 kilometre içinde uygun bir kafe bulunamadı"}

        # Mesafeye göre sırala ve en kısa mesafeye sahip iki kafeyi seç
        cafes_with_distances.sort(key=lambda x: x[1])  # Mesafeye göre sırala
        unique_cafes = []
        seen_places = set()

        for cafe, distance in cafes_with_distances:
            if cafe["place_id"] not in seen_places:
                unique_cafes.append((cafe, distance))
                seen_places.add(cafe["place_id"])
            if len(unique_cafes) == 2:  # Yalnızca en yakın iki kafeyi al
                break

        if len(unique_cafes) < 2:
            return {"error": "Yeterli sayıda benzersiz kafe bulunamadı"}

        # Sadece en yakın iki kafeyi formatla ve döndür
        results = []
        for cafe, distance in unique_cafes:
            google_maps_link = f"https://www.google.com/maps/place/?q=place_id:{cafe['place_id']}"
            results.append({
                "name": cafe["name"],
                "address": cafe.get("vicinity", "Adres bilgisi yok"),
                "distance_meters": round(distance, 2),
                "google_maps_link": google_maps_link
            })

        # Sadece en yakın iki kafeyi konsola yazdır
        print("En Yakın 2 Kafe:")
        for result in results:
            print(result)

        return results

if __name__ == "__main__":
    # Kullanıcıdan konum bilgisi al
    try:
        latitude = input("Enter latitude: ")
        longitude = input("Enter longitude: ")
        service = CafeRecommendationService()
        result = service.find_nearest_cafes(latitude, longitude)
        print(result)
    except Exception as e:
        print(f"Error: {e}")