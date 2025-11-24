from rest_framework import serializers
from .models import Reading, Sensor

class ReadingSerializer(serializers.ModelSerializer):
    sensor = serializers.SlugRelatedField(
        slug_field="name", queryset=Sensor.objects.all()
    )
    class Meta:
        model = Reading
        fields = ["id", "sensor", "temperature", "humidity", "created_at"]

class SensorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sensor
        fields = ["id", "name", "ip_address"]
