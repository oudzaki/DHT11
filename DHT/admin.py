from django.contrib import admin

from .models import Sensor, Reading

@admin.register(Sensor)
class SensorAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "ip_address")
    search_fields = ("name",)

@admin.register(Reading)
class ReadingAdmin(admin.ModelAdmin):
    list_display = ("id", "sensor", "temperature", "humidity", "created_at")
    list_filter = ("sensor", "created_at")
    search_fields = ("sensor__name",)
