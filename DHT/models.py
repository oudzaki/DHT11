from django.conf import settings
from django.db import models

class Sensor(models.Model):
    name = models.CharField(max_length=100, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)  # optionnel si tu « pull »
    shared_key = models.CharField(max_length=128, blank=True, default="")  # clé simple si tu « push »

    def __str__(self):
        return self.name

class Reading(models.Model):
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, related_name="readings")
    temperature = models.FloatField()
    humidity = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

