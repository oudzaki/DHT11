import json
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from rest_framework import generics, permissions
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Reading, Sensor
from .serializers import ReadingSerializer, SensorSerializer
from .permissions import IsAdmin

from datetime import datetime, timedelta
from django.utils.dateparse import parse_datetime, parse_date
from django.utils import timezone

from .alerts_services import get_or_create_open_alert_for_sensor

from .alerts_services import get_or_create_open_alert_for_sensor


# -----------------------------
# Web pages (html)
# -----------------------------
class HomeView(View):
    def get(self, request):
        return render(request, "home.html")


class DashboardView(View):
    def get(self, request):
        return render(request, "dashboard.html")


# -----------------------------
# Push ESP -> Django
# -----------------------------
@method_decorator(csrf_exempt, name="dispatch")
class SensorPushView(View):
    def post(self, request):
        try:
            key = request.headers.get("X-API-KEY")
            if key != settings.SENSOR_API_KEY:
                return JsonResponse({"error": "Unauthorized"}, status=401)

            data = json.loads(request.body)
            name = data.get("sensor")
            temp = data.get("temperature")
            hum = data.get("humidity")

            sensor, _ = Sensor.objects.get_or_create(name=name)
            reading = Reading.objects.create(sensor=sensor, temperature=temp, humidity=hum)
            # Create / update OPEN alert if out-of-range (1 OPEN alert per sensor)            
            get_or_create_open_alert_for_sensor(sensor, reading)

            return JsonResponse({"status": "ok", "id": reading.id})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)


# -----------------------------
# Helpers (fixed thresholds)
# -----------------------------
def compute_sensor_state_from_latest(latest_reading: Reading | None) -> str:
    """
    Return OK or ALERT based on fixed thresholds.
    Defaults can be overridden in settings.py:
      TEMP_MIN = 2.0
      TEMP_MAX = 8.0
    """
    if latest_reading is None:
        return "UNKNOWN"

    temp_min = getattr(settings, "TEMP_MIN", 2.0)
    temp_max = getattr(settings, "TEMP_MAX", 8.0)

    return "ALERT" if (latest_reading.temperature < temp_min or latest_reading.temperature > temp_max) else "OK"


# -----------------------------
# 2) Capteurs / Frigos
# -----------------------------

class SensorListCreate(generics.ListCreateAPIView):
    """
    GET  /api/sensors/        -> public
    POST /api/sensors/        -> admin only
    """
    queryset = Sensor.objects.all().order_by("id")
    serializer_class = SensorSerializer

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated(), IsAdmin()]


class SensorDetail(generics.RetrieveUpdateDestroyAPIView):
    """
    GET           /api/sensors/{id}/  -> public
    PUT/PATCH     /api/sensors/{id}/  -> admin only
    DELETE        /api/sensors/{id}/  -> admin only
    """
    queryset = Sensor.objects.all()
    serializer_class = SensorSerializer

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated(), IsAdmin()]


class SensorStatusView(APIView):
    """
    GET /api/sensors/{id}/status/
    -> last ping (we use latest reading time)
    -> last state OK/ALERT/UNKNOWN
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk: int):
        try:
            sensor = Sensor.objects.get(pk=pk)
        except Sensor.DoesNotExist:
            return Response({"detail": "Sensor not found"}, status=404)

        latest = sensor.readings.order_by("-created_at").first()
        state = compute_sensor_state_from_latest(latest)

        return Response({
            "sensor": {
                "id": sensor.id,
                "name": sensor.name,
            },
            "lastPing": latest.created_at if latest else None,
            "status": state,  # OK / ALERT / UNKNOWN
        })


class SensorLatestMeasurementView(APIView):
    """
    GET /api/sensors/{id}/latest-measurement/
    -> last temperature/humidity + time + status
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk: int):
        try:
            sensor = Sensor.objects.get(pk=pk)
        except Sensor.DoesNotExist:
            return Response({"detail": "Sensor not found"}, status=404)

        latest = sensor.readings.order_by("-created_at").first()
        if not latest:
            return Response({
                "sensor": {"id": sensor.id, "name": sensor.name},
                "temperature": None,
                "humidity": None,
                "createdAt": None,
                "status": "UNKNOWN",
            })

        return Response({
            "sensor": {"id": sensor.id, "name": sensor.name},
            "temperature": latest.temperature,
            "humidity": latest.humidity,
            "createdAt": latest.created_at,
            "status": compute_sensor_state_from_latest(latest),  # OK / ALERT
        })


# -----------------------------
# 3) Readings (existing)
# -----------------------------



class ReadingListCreate(generics.ListCreateAPIView):
    queryset = Reading.objects.order_by("-created_at")
    serializer_class = ReadingSerializer

    def get_permissions(self):
        # GET/HEAD/OPTIONS publics pour lecture du dashboard
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [permissions.AllowAny()]
        # POST protégé
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = Reading.objects.select_related("sensor").all()

        # ---------- Filters ----------
        sensor_id = self.request.query_params.get("sensor_id")
        sensor_name = self.request.query_params.get("sensor_name")

        if sensor_id:
            qs = qs.filter(sensor_id=sensor_id)

        if sensor_name:
            qs = qs.filter(sensor__name=sensor_name)

        # date_from / date_to:
        # Accept formats:
        # - YYYY-MM-DD
        # - ISO datetime: 2026-01-03T10:20:00Z
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        if date_from:
            dt_from = parse_datetime(date_from)
            if dt_from is None:
                d = parse_date(date_from)
                if d:
                    dt_from = datetime(d.year, d.month, d.day, 0, 0, 0)
            if dt_from:
                if timezone.is_naive(dt_from):
                    dt_from = timezone.make_aware(dt_from, timezone.get_current_timezone())
                qs = qs.filter(created_at__gte=dt_from)

        if date_to:
            dt_to = parse_datetime(date_to)
            if dt_to is None:
                d = parse_date(date_to)
                if d:
                    # include the full day (23:59:59)
                    dt_to = datetime(d.year, d.month, d.day, 23, 59, 59)
            if dt_to:
                if timezone.is_naive(dt_to):
                    dt_to = timezone.make_aware(dt_to, timezone.get_current_timezone())
                qs = qs.filter(created_at__lte=dt_to)

        # ---------- Ordering ----------
        ordering = self.request.query_params.get("ordering", "-created_at")
        if ordering in ("created_at", "-created_at"):
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by("-created_at")

        return qs



class ReadingLatest(generics.RetrieveAPIView):
    serializer_class = ReadingSerializer
    permission_classes = [permissions.AllowAny]

    def get_object(self):
        sensor_name = self.kwargs["sensor_name"]
        return Reading.objects.filter(sensor__name=sensor_name).order_by("-created_at").first()
