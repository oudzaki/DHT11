from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Sensor(models.Model):
    name = models.CharField(max_length=100, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)  # optional if you "pull"
    shared_key = models.CharField(max_length=128, blank=True, default="")  # optional if you "push"

    def __str__(self) -> str:
        return self.name


class Reading(models.Model):
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, related_name="readings")
    temperature = models.FloatField()
    humidity = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.sensor.name} @ {self.created_at}"


class UserProfile(models.Model):
    STATUS_ACTIVE = "ACTIVE"
    STATUS_INACTIVE = "INACTIVE"

    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")

    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Phone number used for notifications (Twilio calls)",
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )

    def __str__(self) -> str:
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

    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, related_name="alerts")

    # Snapshot values (keep context even if readings change)
    temperature = models.FloatField(null=True, blank=True)
    humidity = models.FloatField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default=SEV_LOW)

    # Escalation level (1=Operator, 2=Manager, 3=Admin)
    level = models.PositiveSmallIntegerField(default=1)

    # Number of notifications sent without ACK for the CURRENT level (0..3)
    tries_without_response = models.PositiveSmallIntegerField(default=0)

    # Scheduling
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)

    # ACK / RESOLVE tracking
    acked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acked_alerts",
    )
    acked_at = models.DateTimeField(null=True, blank=True)

    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_alerts",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["sensor", "status"]),
            models.Index(fields=["status", "next_retry_at"]),
            models.Index(fields=["created_at"]),
        ]

    def is_open(self) -> bool:
        return self.status == self.STATUS_OPEN

    def __str__(self) -> str:
        return f"Alert#{self.id} {self.sensor.name} {self.status} L{self.level} T{self.tries_without_response}"


class AlertNotificationLog(models.Model):
    """
    Audit of notifications sent (email now, call later).
    """
    CHANNEL_EMAIL = "EMAIL"
    CHANNEL_CALL = "CALL"

    CHANNEL_CHOICES = (
        (CHANNEL_EMAIL, "Email"),
        (CHANNEL_CALL, "Call"),
    )

    STATUS_SENT = "SENT"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = (
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
    )

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="notification_logs")
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default=CHANNEL_EMAIL)

    # Snapshot of recipients at send time (simple comma-separated list)
    recipients = models.TextField(blank=True, default="")

    # Attempt number for the CURRENT level (1..3)
    attempt_number = models.PositiveSmallIntegerField(default=1)

    sent_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SENT)
    error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["alert", "sent_at"]),
            models.Index(fields=["channel", "status"]),
        ]

    def __str__(self) -> str:
        return f"Alert#{self.alert_id} {self.channel} attempt={self.attempt_number} {self.status}"


class Ticket(models.Model):
    """
    Ticket = human work item (tracking intervention).
    1 ticket per alert (OneToOne).
    Created automatically when alert reaches level 3 (ADMIN), or manually from the UI.
    """
    STATUS_OPEN = "OPEN"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_CLOSED = "CLOSED"

    STATUS_CHOICES = (
        (STATUS_OPEN, "Open"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_CLOSED, "Closed"),
    )

    PRIORITY_LOW = "LOW"
    PRIORITY_MEDIUM = "MEDIUM"
    PRIORITY_HIGH = "HIGH"

    PRIORITY_CHOICES = (
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_HIGH, "High"),
    )

    alert = models.OneToOneField(
        Alert,
        on_delete=models.CASCADE,
        related_name="ticket",
    )

    title = models.CharField(max_length=200, default="")
    description = models.TextField(blank=True, default="")

    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)

    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tickets",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["priority", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Ticket#{self.id} alert={self.alert_id} {self.status}"
