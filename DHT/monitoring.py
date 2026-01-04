from __future__ import annotations

import os
from datetime import timedelta
from typing import Tuple, List

from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.mail import send_mail

from vonage import Auth, Vonage
from vonage_voice import CreateCallRequest, Phone, Talk, ToPhone

from .models import (
    Alert,
    AlertNotificationLog,
    Reading,
    Sensor,
    UserProfile,
    Ticket,
)

# ============================================================
# CONFIG
# ============================================================

DEFAULT_TEMP_MIN = 2.0
DEFAULT_TEMP_MAX = 8.0

DEFAULT_ESCALATION_COUNT = 3
DEFAULT_RETRY_DELAY_MINUTES = 1
DEFAULT_REPEAT_DELAY_MINUTES_LEVEL3 = 30


def get_monitoring_config() -> dict:
    return {
        "temp_min": float(getattr(settings, "TEMP_MIN", DEFAULT_TEMP_MIN)),
        "temp_max": float(getattr(settings, "TEMP_MAX", DEFAULT_TEMP_MAX)),
        "escalation_count": int(getattr(settings, "ESCALATION_COUNT", DEFAULT_ESCALATION_COUNT)),
        "retry_delay": int(getattr(settings, "RETRY_DELAY_MINUTES", DEFAULT_RETRY_DELAY_MINUTES)),
        "repeat_delay_l3": int(getattr(settings, "REPEAT_DELAY_MINUTES_LEVEL3", DEFAULT_REPEAT_DELAY_MINUTES_LEVEL3)),
    }


# ============================================================
# UTILS
# ============================================================

def is_out_of_range(temp: float | None) -> bool:
    if temp is None:
        return False
    cfg = get_monitoring_config()
    return temp < cfg["temp_min"] or temp > cfg["temp_max"]


def compute_severity(temp: float | None) -> str:
    if temp is None:
        return Alert.SEV_LOW

    cfg = get_monitoring_config()
    delta = max(abs(temp - cfg["temp_min"]), abs(temp - cfg["temp_max"]))

    if delta >= 5:
        return Alert.SEV_HIGH
    if delta >= 2:
        return Alert.SEV_MED
    return Alert.SEV_LOW


def role_for_level(level: int) -> str:
    if level == 1:
        return "OPERATOR"
    if level == 2:
        return "MANAGER"
    return "ADMIN"


# ============================================================
# RECIPIENTS
# ============================================================

def get_email_recipients(level: int) -> List[User]:
    role = role_for_level(level)
    qs = User.objects.filter(is_active=True)

    if role == "ADMIN":
        qs = qs.filter(is_superuser=True)
    elif role == "MANAGER":
        qs = qs.filter(is_staff=True, is_superuser=False)
    else:
        qs = qs.filter(is_staff=False, is_superuser=False)

    users = []
    for u in qs:
        profile, _ = UserProfile.objects.get_or_create(user=u)
        if profile.status == UserProfile.STATUS_ACTIVE and u.email:
            users.append(u)
    return users


def get_call_recipients(level: int) -> List[str]:
    phones: list[str] = []
    for u in get_email_recipients(level):
        profile, _ = UserProfile.objects.get_or_create(user=u)
        if profile.phone:
            phones.append(profile.phone.lstrip("+"))  # Vonage => no +
    return phones


# ============================================================
# EMAIL
# ============================================================

def send_alert_email(alert: Alert, users: List[User]) -> tuple[bool, str]:
    if not users:
        return False, "No email recipients"

    subject = f"⚠️ Alert L{alert.level} – {alert.sensor.name}"
    message = (
        f"Sensor: {alert.sensor.name}\n"
        f"Temperature: {alert.temperature}\n"
        f"Severity: {alert.severity}\n"
        f"Level: {alert.level}\n"
        f"Created at: {alert.created_at}\n"
    )

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [u.email for u in users],
            fail_silently=False,
        )
        return True, ""
    except Exception as e:
        return False, str(e)


# ============================================================
# VONAGE VOICE
# ============================================================

def _read_private_key(key: str) -> str:
    if key.startswith("-----BEGIN"):
        return key
    with open(key, "r", encoding="utf-8") as f:
        return f.read()


def vonage_client() -> Vonage:
    key = _read_private_key(settings.VONAGE_PRIVATE_KEY)
    return Vonage(Auth(
        application_id=settings.VONAGE_APPLICATION_ID,
        private_key=key,
    ))


def send_alert_call(alert: Alert, phones: List[str]) -> tuple[bool, str]:
    if not phones:
        return False, "No phone recipients"

    try:
        client = vonage_client()
        for phone in phones:
            client.voice.create_call(
                CreateCallRequest(
                    ncco=[Talk(text=f"Alert level {alert.level}. Sensor {alert.sensor.name}. Temperature {alert.temperature}.")],
                    to=[ToPhone(number=phone)],
                    from_=Phone(number=settings.VONAGE_VIRTUAL_NUMBER),
                )
            )
        return True, ""
    except Exception as e:
        return False, str(e)


# ============================================================
# ALERT LIFECYCLE
# ============================================================

def get_or_create_alert(sensor: Sensor, reading: Reading) -> Alert | None:
    if not is_out_of_range(reading.temperature):
        return None

    alert = Alert.objects.filter(sensor=sensor, status=Alert.STATUS_OPEN).first()

    if alert:
        alert.temperature = reading.temperature
        alert.severity = compute_severity(reading.temperature)
        alert.save()
        return alert

    return Alert.objects.create(
        sensor=sensor,
        temperature=reading.temperature,
        severity=compute_severity(reading.temperature),
        status=Alert.STATUS_OPEN,
        level=1,
        tries_without_response=0,
        next_retry_at=timezone.now(),
    )


def ensure_ticket(alert: Alert):
    if alert.level < 3:
        return
    Ticket.objects.get_or_create(
        alert=alert,
        defaults={
            "title": f"Critical alert {alert.sensor.name}",
            "status": Ticket.STATUS_OPEN,
            "priority": Ticket.PRIORITY_HIGH,
        }
    )


# ============================================================
# MAIN PROCESSOR
# ============================================================

def process_due_alert(alert: Alert):
    if alert.status != Alert.STATUS_OPEN:
        return

    now = timezone.now()
    if alert.next_retry_at and now < alert.next_retry_at:
        return

    cfg = get_monitoring_config()

    emails = get_email_recipients(alert.level)
    phones = get_call_recipients(alert.level)

    ok_e, err_e = send_alert_email(alert, emails)
    ok_c, err_c = send_alert_call(alert, phones)

    AlertNotificationLog.objects.create(
        alert=alert,
        level=alert.level,
        email_ok=ok_e,
        call_ok=ok_c,
        error=(err_e or err_c),
    )

    alert.tries_without_response += 1

    if alert.tries_without_response >= cfg["escalation_count"]:
        if alert.level < 3:
            alert.level += 1
            alert.tries_without_response = 0
            ensure_ticket(alert)
        alert.next_retry_at = now + timedelta(minutes=cfg["repeat_delay_l3"])
    else:
        alert.next_retry_at = now + timedelta(minutes=cfg["retry_delay"])

    alert.last_notified_at = now
    alert.save()
