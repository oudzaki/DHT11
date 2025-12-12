from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from .models import Reading, Sensor
from .serializers import ReadingSerializer, SensorSerializer
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
#from .api_key import API_KEY
from django.conf import settings
from django.shortcuts import render
from django.core.mail import send_mail
from django.conf import settings

import json

@method_decorator(csrf_exempt, name='dispatch')
class SensorPushView(View):
    def post(self, request):
        try:
            #key = request.headers.get("X-API-KEY")
            key = request.headers.get("X-API-KEY")
            #if key != API_KEY:
            if key != settings.SENSOR_API_KEY:
                return JsonResponse({"error": "Unauthorized"}, status=401)

            data = json.loads(request.body)
            name = data.get("sensor")
            temp = data.get("temperature")
            hum = data.get("humidity")

            sensor, _ = Sensor.objects.get_or_create(name=name)
            reading = Reading.objects.create(sensor=sensor, temperature=temp, humidity=hum)

            return JsonResponse({"status": "ok", "id": reading.id})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

# @method_decorator(csrf_exempt, name="dispatch")
# class SensorPushView(View):
#     def post(self, request):
#         key = request.headers.get("X-API-KEY")
#         if key != settings.SENSOR_API_KEY:
#             return JsonResponse({"error": "Unauthorized"}, status=401)

#         try:
#             data = json.loads(request.body)
#             sensor_name = data.get("sensor")
#             temperature = float(data.get("temperature"))
#             humidity = float(data.get("humidity"))
#         except Exception as e:
#             return JsonResponse({"error": f"Bad request: {e}"}, status=400)

#         sensor, _ = Sensor.objects.get_or_create(name=sensor_name)
#         reading = Reading.objects.create(sensor=sensor, temperature=temperature, humidity=humidity)

#         # ⚠️ Si la température < 25°C → envoyer un mail
#         if temperature < 25:
#             subject = f"⚠️ Température basse détectée ({temperature:.1f}°C)"
#             message = (
#                 f"Alerte automatique du capteur {sensor_name}\n\n"
#                 f"Température: {temperature:.1f}°C\n"
#                 f"Humidité: {humidity:.1f}%\n"
#                 f"Heure: {reading.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
#             )
#             send_mail(
#                 subject,
#                 message,
#                 settings.DEFAULT_FROM_EMAIL,
#                 settings.ALERT_RECIPIENTS,
#                 fail_silently=False,
#             )

#         return JsonResponse({"status": "ok", "id": reading.id})


class HomeView(View):
    def get(self, request):
        # return JsonResponse({
        #     "app": "DHT API",
        #     "endpoints": [
        #         "/api/auth/token/",
        #         "/api/sensors/",
        #         "/api/readings/",
        #         "/api/readings/latest/<sensor_name>/",
        #         "/api/push/"
        #     ]
        # })
        return render(request, "home.html")

class DashboardView(View):
    def get(self, request):
        return render(request, "dashboard.html")  # ou "index.html"





class ReadingListCreate(generics.ListCreateAPIView):
    queryset = Reading.objects.order_by("-created_at")
    serializer_class = ReadingSerializer

    def get_permissions(self):
        # GET/HEAD/OPTIONS publics pour lecture du dashboard
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [permissions.AllowAny()]
        # POST (via DRF) reste protégé si tu l’utilises un jour
        return [permissions.IsAuthenticated()]


class ReadingLatest(generics.RetrieveAPIView):
    serializer_class = ReadingSerializer

    # Dernière mesure d’un capteur : lecture publique
    permission_classes = [permissions.AllowAny]

    def get_object(self):
        sensor_name = self.kwargs["sensor_name"]
        return Reading.objects.filter(sensor__name=sensor_name).order_by("-created_at").first()


class SensorListCreate(generics.ListCreateAPIView):
    queryset = Sensor.objects.all()
    serializer_class = SensorSerializer

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]
