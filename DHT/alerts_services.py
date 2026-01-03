from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.mail import send_mail

from .models import Alert, AlertNotificationLog, Reading, Sensor, UserProfile

# ------------------------------------------------------------
# Config helpers
# ------------------------------------------------------------

DEFAULT_TEMP_MIN = 2.0
DEFAULT_TEMP_MAX = 8.0

DEFAULT_ESCALATION_COUNT = 3
DEFAULT_RETRY_DELAY_MINUTES = 5
DEFAULT_REPEAT_DELAY_MINUTES_LEVEL3 = 30


def get_monitoring_config() -> dict:
    temp_min = float(getattr(settings, "TEMP_MIN", DEFAULT_TEMP_MIN))
    temp_max = float(getattr(settings, "TEMP_MAX", DEFAULT_TEMP_MAX))

    escalation_count = int(getattr(settings, "ESCALATION_COUNT", DEFAULT_ESCALATION_COUNT))
    retry_delay_min = int(getattr(settings, "RETRY_DELAY_MINUTES", DEFAULT_RETRY_DELAY_MINUTES))
    repeat_delay_min = int(getattr(settings, "REPEAT_DELAY_MINUTES_LEVEL3", DEFAULT_REPEAT_DELAY_MINUTES_LEVEL3))

    # Guard rails
    escalation_count = max(1, escalation_count)
    retry_delay_min = max(1, retry_delay_min)
    repeat_delay_min = max(1, repeat_delay_min)

    return {
        "tempMin": temp_min,
        "tempMax": temp_max,
        "escalationCount": escalation_count,
        "retryDelayMinutes": retry_delay_min,
        "repeatDelayMinutesLevel3": repeat_delay_min,
    }


# ------------------------------------------------------------
# Rules
# ------------------------------------------------------------

def compute_severity(temp: float | None) -> str:
    """
    Fixed severity based on delta to thresholds.
    """
    if temp is None:
        return Alert.SEV_LOW

    cfg = get_monitoring_config()
    temp_min = cfg["tempMin"]
    temp_max = cfg["tempMax"]

    if temp < temp_min:
        delta = temp_min - temp
    elif temp > temp_max:
        delta = temp - temp_max
    else:
        delta = 0.0

    if delta >= 5:
        return Alert.SEV_HIGH
    if delta >= 2:
        return Alert.SEV_MED
    return Alert.SEV_LOW


def is_out_of_range(temp: float | None) -> bool:
    if temp is None:
        return False
    cfg = get_monitoring_config()
    return temp < cfg["tempMin"] or temp > cfg["tempMax"]


def role_for_level(level: int) -> str:
    # Fixed mapping (as decided)
    if level <= 1:
        return "OPERATOR"
    if level == 2:
        return "MANAGER"
    return "ADMIN"


def user_role(user: User) -> str:
    if user.is_superuser:
        return "ADMIN"
    if user.is_staff:
        return "MANAGER"
    return "OPERATOR"


# ------------------------------------------------------------
# Recipients selection
# ------------------------------------------------------------

def get_recipients_for_level(level: int) -> list[User]:
    """
    Select ACTIVE users by role + must have email for email notifications.
    Also guarantees UserProfile exists to avoid RelatedObjectDoesNotExist.
    """
    target_role = role_for_level(level)

    users_qs = User.objects.filter(is_active=True)

    if target_role == "ADMIN":
        users_qs = users_qs.filter(is_superuser=True)
    elif target_role == "MANAGER":
        users_qs = users_qs.filter(is_superuser=False, is_staff=True)
    else:
        users_qs = users_qs.filter(is_superuser=False, is_staff=False)

    recipients: list[User] = []
    for u in users_qs:
        profile, _ = UserProfile.objects.get_or_create(user=u)
        if profile.status == UserProfile.STATUS_ACTIVE and u.email:
            recipients.append(u)

    return recipients


# ------------------------------------------------------------
# Alert creation/update (1 OPEN alert per sensor)
# ------------------------------------------------------------

def get_or_create_open_alert_for_sensor(sensor: Sensor, reading: Reading) -> Alert | None:
    """
    Rule: 1 OPEN alert per sensor.
    Only create/update alert if the reading is out-of-range.
    """
    if not is_out_of_range(reading.temperature):
        return None

    alert = (
        Alert.objects
        .filter(sensor=sensor, status=Alert.STATUS_OPEN)
        .order_by("-created_at")
        .first()
    )

    if alert:
        alert.temperature = reading.temperature
        alert.humidity = reading.humidity
        alert.severity = compute_severity(reading.temperature)
        alert.save(update_fields=["temperature", "humidity", "severity", "updated_at"])
        return alert

    now = timezone.now()
    return Alert.objects.create(
        sensor=sensor,
        temperature=reading.temperature,
        humidity=reading.humidity,
        severity=compute_severity(reading.temperature),
        status=Alert.STATUS_OPEN,
        level=1,
        tries_without_response=0,
        next_retry_at=now,  # eligible immediately for first notify
    )


# ------------------------------------------------------------
# Email sending
# ------------------------------------------------------------

def build_email(alert: Alert) -> tuple[str, str]:
    cfg = get_monitoring_config()
    subject = f"⚠️ Cold Chain Alert [{alert.sensor.name}] - {alert.severity} - Level {alert.level}"
    message = (
        f"Alert ID: {alert.id}\n"
        f"Sensor: {alert.sensor.name}\n"
        f"Status: {alert.status}\n"
        f"Severity: {alert.severity}\n"
        f"Escalation Level: {alert.level}\n"
        f"Temperature: {alert.temperature}\n"
        f"Humidity: {alert.humidity}\n"
        f"Thresholds: {cfg['tempMin']} .. {cfg['tempMax']}\n"
        f"Created At: {alert.created_at}\n\n"
        f"Action required: Please ACK in the web app to stop escalation.\n"
        f"ACK endpoint: POST /api/alerts/{alert.id}/ack/\n"
        f"Resolve endpoint: POST /api/alerts/{alert.id}/resolve/\n"
    )
    return subject, message


def send_alert_email(alert: Alert, recipients: list[User]) -> tuple[bool, str]:
    if not recipients:
        return False, "No recipients found for this level."

    subject, message = build_email(alert)
    emails = [u.email for u in recipients if u.email]

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
    if not from_email:
        return False, "DEFAULT_FROM_EMAIL is not configured in settings.py"

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=emails,
            fail_silently=False,
        )
        return True, ""
    except Exception as e:
        return False, str(e)


# ------------------------------------------------------------
# Processing (retry/escalation/repeat logic)
# ------------------------------------------------------------

def process_due_alert(alert: Alert) -> None:
    """
    Rules:
    - retry delay = 5 min (config)
    - escalation after 3 tries without ACK (config)
    - once level 3 reached and tries==3 => repeat every 30 min (config)
    """
    if alert.status != Alert.STATUS_OPEN:
        return

    now = timezone.now()

    if alert.next_retry_at and now < alert.next_retry_at:
        return

    cfg = get_monitoring_config()
    escalation_count: int = cfg["escalationCount"]
    retry_delay_min: int = cfg["retryDelayMinutes"]
    repeat_delay_min: int = cfg["repeatDelayMinutesLevel3"]

    # ---------- Level 3 repeat mode (tries already reached escalation_count) ----------
    if alert.level >= 3 and alert.tries_without_response >= escalation_count:
        recipients = get_recipients_for_level(3)
        ok, err = send_alert_email(alert, recipients)

        AlertNotificationLog.objects.create(
            alert=alert,
            channel=AlertNotificationLog.CHANNEL_EMAIL,
            recipients=",".join([u.email for u in recipients]),
            attempt_number=escalation_count,
            status=AlertNotificationLog.STATUS_SENT if ok else AlertNotificationLog.STATUS_FAILED,
            error=err,
        )

        alert.last_notified_at = now
        alert.next_retry_at = now + timezone.timedelta(minutes=repeat_delay_min)
        alert.save(update_fields=["last_notified_at", "next_retry_at", "updated_at"])
        return

    # ---------- Normal flow ----------
    recipients = get_recipients_for_level(alert.level)
    ok, err = send_alert_email(alert, recipients)

    attempt_number = min(alert.tries_without_response + 1, escalation_count)

    AlertNotificationLog.objects.create(
        alert=alert,
        channel=AlertNotificationLog.CHANNEL_EMAIL,
        recipients=",".join([u.email for u in recipients]),
        attempt_number=attempt_number,
        status=AlertNotificationLog.STATUS_SENT if ok else AlertNotificationLog.STATUS_FAILED,
        error=err,
    )

    alert.last_notified_at = now

    # Increment tries (cap)
    alert.tries_without_response = min(alert.tries_without_response + 1, escalation_count)

    # If reached max tries => escalate or enter repeat mode
    if alert.tries_without_response >= escalation_count:
        if alert.level < 3:
            alert.level += 1
            alert.tries_without_response = 0
            alert.next_retry_at = now  # notify next level immediately on next run
        else:
            # at level 3 and just hit tries==3 => schedule repeat
            alert.next_retry_at = now + timezone.timedelta(minutes=repeat_delay_min)
    else:
        # retry same level after 5 minutes
        alert.next_retry_at = now + timezone.timedelta(minutes=retry_delay_min)

    alert.save(update_fields=["tries_without_response", "level", "last_notified_at", "next_retry_at", "updated_at"])
