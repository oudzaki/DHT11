from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.mail import send_mail

from .models import Alert, AlertNotificationLog, Reading, Sensor, UserProfile


def get_monitoring_config():
    temp_min = getattr(settings, "TEMP_MIN", 2.0)
    temp_max = getattr(settings, "TEMP_MAX", 8.0)

    escalation_count = getattr(settings, "ESCALATION_COUNT", 3)  # fixed: 3
    retry_delay_min = getattr(settings, "RETRY_DELAY_MINUTES", 5)  # fixed: 5 min
    repeat_delay_min = getattr(settings, "REPEAT_DELAY_MINUTES_LEVEL3", 30)  # fixed: 30 min

    return {
        "tempMin": temp_min,
        "tempMax": temp_max,
        "escalationCount": escalation_count,
        "retryDelayMinutes": retry_delay_min,
        "repeatDelayMinutesLevel3": repeat_delay_min,
    }


def compute_severity(temp: float | None) -> str:
    """
    Simple fixed severity based on delta from thresholds.
    You can refine later.
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
        delta = 0

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
    if level == 1:
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


def get_recipients_for_level(level: int) -> list[User]:
    """
    Select ACTIVE users by role + must have email for email notifications.
    """
    target_role = role_for_level(level)

    # Filter active users only
    users_qs = User.objects.filter(is_active=True)

    if target_role == "ADMIN":
        users_qs = users_qs.filter(is_superuser=True)
    elif target_role == "MANAGER":
        users_qs = users_qs.filter(is_superuser=False, is_staff=True)
    else:
        users_qs = users_qs.filter(is_superuser=False, is_staff=False)

    # Must have profile ACTIVE
    active_ids = []
    for u in users_qs:
        profile, _ = UserProfile.objects.get_or_create(user=u)
        if profile.status == "ACTIVE":
            active_ids.append(u.id)

    users_qs = users_qs.filter(id__in=active_ids).exclude(email__isnull=True).exclude(email__exact="")

    return list(users_qs)


def get_or_create_open_alert_for_sensor(sensor: Sensor, reading: Reading) -> Alert | None:
    """
    Rule: 1 OPEN alert per sensor.
    Only create alert if reading is out-of-range.
    """
    if not is_out_of_range(reading.temperature):
        return None

    alert = Alert.objects.filter(sensor=sensor, status=Alert.STATUS_OPEN).order_by("-created_at").first()
    if alert:
        # Update snapshot values to latest bad reading
        alert.temperature = reading.temperature
        alert.humidity = reading.humidity
        alert.severity = compute_severity(reading.temperature)
        alert.save(update_fields=["temperature", "humidity", "severity", "updated_at"])
        return alert

    # Create a new OPEN alert
    now = timezone.now()
    alert = Alert.objects.create(
        sensor=sensor,
        temperature=reading.temperature,
        humidity=reading.humidity,
        severity=compute_severity(reading.temperature),
        status=Alert.STATUS_OPEN,
        level=1,
        tries_without_response=0,
        next_retry_at=now,  # immediately eligible for first notify
    )
    return alert


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

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            emails,
            fail_silently=False,
        )
        return True, ""
    except Exception as e:
        return False, str(e)


def process_due_alert(alert: Alert) -> None:
    """
    Applies: escalation_count=3
    - If OPEN and due (now >= next_retry_at), send email
    - Increment tries up to 3
    - If tries reaches 3 -> escalate to next level, reset tries=0, notify again (next run or immediately by setting next_retry_at=now)
    - If at level 3 and tries already 3 -> repeat every 30 minutes (no more increment)
    """
    if alert.status != Alert.STATUS_OPEN:
        return

    now = timezone.now()
    if alert.next_retry_at and now < alert.next_retry_at:
        return

    cfg = get_monitoring_config()
    escalation_count = cfg["escalationCount"]
    retry_delay = cfg["retryDelayMinutes"]
    repeat_delay = cfg["repeatDelayMinutesLevel3"]

    # Level 3 repeating mode: once tries == 3, we keep repeating every 30min
    if alert.level == 3 and alert.tries_without_response >= escalation_count:
        recipients = get_recipients_for_level(3)
        ok, err = send_alert_email(alert, recipients)

        AlertNotificationLog.objects.create(
            alert=alert,
            channel=AlertNotificationLog.CHANNEL_EMAIL,
            recipients=",".join([u.email for u in recipients]),
            attempt_number=escalation_count,
            status="SENT" if ok else "FAILED",
            error=err,
        )

        alert.last_notified_at = now
        alert.next_retry_at = now + timezone.timedelta(minutes=repeat_delay)
        alert.save(update_fields=["last_notified_at", "next_retry_at", "updated_at"])
        return

    # Normal flow (levels 1..3, tries 0..2)
    recipients = get_recipients_for_level(alert.level)
    ok, err = send_alert_email(alert, recipients)

    # attempt number is tries+1 (because we're about to increment)
    attempt_number = min(alert.tries_without_response + 1, escalation_count)

    AlertNotificationLog.objects.create(
        alert=alert,
        channel=AlertNotificationLog.CHANNEL_EMAIL,
        recipients=",".join([u.email for u in recipients]),
        attempt_number=attempt_number,
        status="SENT" if ok else "FAILED",
        error=err,
    )

    # Increment tries (cap to escalation_count)
    alert.tries_without_response = min(alert.tries_without_response + 1, escalation_count)
    alert.last_notified_at = now

    # If reached 3 tries -> escalate
    if alert.tries_without_response >= escalation_count:
        if alert.level < 3:
            alert.level += 1
            alert.tries_without_response = 0
            alert.next_retry_at = now  # eligible immediately for next level notify
        else:
            # now at level 3 and tries == 3 -> switch to repeat mode
            alert.next_retry_at = now + timezone.timedelta(minutes=repeat_delay)
    else:
        # retry same level after 5 minutes
        alert.next_retry_at = now + timezone.timedelta(minutes=retry_delay)

    alert.save(update_fields=["tries_without_response", "level", "last_notified_at", "next_retry_at", "updated_at"])
