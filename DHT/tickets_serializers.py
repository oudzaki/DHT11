from rest_framework import serializers
from django.utils import timezone

from .models import Ticket, Alert


class TicketSerializer(serializers.ModelSerializer):
    alert = serializers.SerializerMethodField()
    assigned_to_username = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = (
            "id",
            "alert",
            "title",
            "description",
            "priority",
            "status",
            "assigned_to",
            "assigned_to_username",
            "created_by",
            "created_at",
            "closed_at",
        )
        read_only_fields = ("created_by", "created_at", "closed_at")

    def get_alert(self, obj: Ticket):
        return {
            "id": obj.alert_id,
            "sensor": {"id": obj.alert.sensor_id, "name": obj.alert.sensor.name},
            "severity": obj.alert.severity,
            "status": obj.alert.status,
            "level": obj.alert.level,
        }

    def get_assigned_to_username(self, obj: Ticket):
        return obj.assigned_to.username if obj.assigned_to else None


class TicketCreateFromAlertSerializer(serializers.Serializer):
    """
    Manual ticket creation: POST /api/tickets/create-from-alert/
    """
    alert_id = serializers.IntegerField()
    title = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=Ticket.PRIORITY_CHOICES, required=False)

    def validate_alert_id(self, value: int):
        try:
            alert = Alert.objects.select_related("sensor").get(id=value)
        except Alert.DoesNotExist:
            raise serializers.ValidationError("Alert not found.")
        if alert.status != Alert.STATUS_OPEN and alert.status != Alert.STATUS_ACK:
            raise serializers.ValidationError("Ticket can only be created from OPEN/ACK alerts.")
        return value
