from rest_framework import serializers
from .models import Alert, AlertNotificationLog


class AlertSerializer(serializers.ModelSerializer):
    sensor = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = (
            "id",
            "sensor",
            "temperature",
            "humidity",
            "status",
            "severity",
            "level",
            "tries_without_response",
            "next_retry_at",
            "last_notified_at",
            "acked_at",
            "resolved_at",
            "created_at",
            "updated_at",
        )

    def get_sensor(self, obj):
        return {"id": obj.sensor_id, "name": obj.sensor.name}


class AlertDetailSerializer(AlertSerializer):
    notification_logs = serializers.SerializerMethodField()

    class Meta(AlertSerializer.Meta):
        fields = AlertSerializer.Meta.fields + ("notification_logs", "acked_by", "resolved_by")

    def get_notification_logs(self, obj):
        logs = obj.notification_logs.order_by("-sent_at")[:50]
        return [
            {
                "id": l.id,
                "channel": l.channel,
                "recipients": l.recipients,
                "attempt_number": l.attempt_number,
                "sent_at": l.sent_at,
                "status": l.status,
                "error": l.error,
            }
            for l in logs
        ]
