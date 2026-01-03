from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

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


class UserProfile(models.Model):
    STATUS_CHOICES = (
        ("ACTIVE", "Active"),
        ("INACTIVE", "Inactive"),
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile"
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Phone number used for notifications (Twilio calls)"
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="ACTIVE"
    )

    def __str__(self):
        return f"{self.user.username} profile"


class Alert(models.Model):
    STATUS_OPEN = "OPEN"
    STATUS_ACK = "ACKNOWLEDGED"
    STATUS_RESOLVED = "RESOLVED"

    STATUS_CHOICES = (
        (STATUS_OPEN, "Open"),
        (STATUS_ACK, "Acknowledged"),
        (STATUS_RESOLVED, "Resolved"),
    )

    SEV_LOW = "LOW"
    SEV_MED = "MEDIUM"
    SEV_HIGH = "HIGH"

    SEVERITY_CHOICES = (
        (SEV_LOW, "Low"),
        (SEV_MED, "Medium"),
        (SEV_HIGH, "High"),
    )

    sensor = models.ForeignKey("Sensor", on_delete=models.CASCADE, related_name="alerts")

    # Snapshot values (so alert detail keeps the triggering context)
    temperature = models.FloatField(null=True, blank=True)
    humidity = models.FloatField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default=SEV_LOW)

    # Escalation level (1=Operator, 2=Manager, 3=Admin)
    level = models.PositiveSmallIntegerField(default=1)

    # Number of notifications sent without ACK (0..3). Capped at 3.
    tries_without_response = models.PositiveSmallIntegerField(default=0)

    # Scheduling
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)

    acked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="acked_alerts"
    )
    acked_at = models.DateTimeField(null=True, blank=True)

    resolved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolved_alerts"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_open(self) -> bool:
        return self.status == self.STATUS_OPEN

    def __str__(self):
        return f"Alert#{self.id} {self.sensor.name} {self.status} L{self.level} T{self.tries_without_response}"


class AlertNotificationLog(models.Model):
    """
    Keeps audit of notifications sent.
    """
    CHANNEL_EMAIL = "EMAIL"
    CHANNEL_CALL = "CALL"

    CHANNEL_CHOICES = (
        (CHANNEL_EMAIL, "Email"),
        (CHANNEL_CALL, "Call"),
    )

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="notification_logs")
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default=CHANNEL_EMAIL)

    # snapshot of recipients at send time (simple string list)
    recipients = models.TextField(blank=True, default="")

    # attempt number for the current level
    attempt_number = models.PositiveSmallIntegerField(default=1)

    sent_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, default="SENT")  # SENT / FAILED
    error = models.TextField(blank=True, default="")

    def __str__(self):
        return f"Alert#{self.alert_id} {self.channel} attempt={self.attempt_number} {self.status}"
