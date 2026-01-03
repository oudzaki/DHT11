from rest_framework import serializers
from .models import Sensor, Reading


class SensorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sensor
        fields = ("id", "name", "ip_address")


class ReadingSerializer(serializers.ModelSerializer):
    sensorName = serializers.CharField(source="sensor.name", read_only=True)

    class Meta:
        model = Reading
        fields = ("id", "sensor", "sensorName", "temperature", "humidity", "created_at")
