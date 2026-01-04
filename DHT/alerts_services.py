from __future__ import annotations

from datetime import timedelta
from typing import Tuple

from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.mail import send_mail

from .models import (
    Alert,
    AlertNotificationLog,
    Reading,
    Sensor,
    UserProfile,
    Ticket,
)

# ------------------------------------------------------------
# Config helpers
# ------------------------------------------------------------

DEFAULT_TEMP_MIN = 2.0
DEFAULT_TEMP_MAX = 8.0

DEFAULT_ESCALATION_COUNT = 3
DEFAULT_RETRY_DELAY_MINUTES = 1
DEFAULT_REPEAT_DELAY_MINUTES_LEVEL3 = 5


def get_monitoring_config() -> dict:
    temp_min = float(getattr(settings, "TEMP_MIN", DEFAULT_TEMP_MIN))
    temp_max = float(getattr(settings, "TEMP_MAX", DEFAULT_TEMP_MAX))

    escalation_count = int(getattr(settings, "ESCALATION_COUNT", DEFAULT_ESCALATION_COUNT))
    retry_delay_min = int(getattr(settings, "RETRY_DELAY_MINUTES", DEFAULT_RETRY_DELAY_MINUTES))
    repeat_delay_min = int(getattr(settings, "REPEAT_DELAY_MINUTES_LEVEL3", DEFAULT_REPEAT_DELAY_MINUTES_LEVEL3))

    return {
        "tempMin": temp_min,
        "tempMax": temp_max,
        "escalationCount": max(1, escalation_count),
        "retryDelayMinutes": max(1, retry_delay_min),
        "repeatDelayMinutesLevel3": max(1, repeat_delay_min),
    }


# ------------------------------------------------------------
# Rules
# ------------------------------------------------------------

def compute_severity(temp: float | None) -> str:
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


# ------------------------------------------------------------
# Roles (exact + cumulative)
# NOTE: this uses Django flags; if you use profile.role, replace filters accordingly.
# ------------------------------------------------------------

def _users_for_role_exact(target_role: str):
    qs = User.objects.filter(is_active=True)

    if target_role == "ADMIN":
        return qs.filter(is_superuser=True)
    if target_role == "MANAGER":
        return qs.filter(is_superuser=False, is_staff=True)
    return qs.filter(is_superuser=False, is_staff=False)  # OPERATOR


def _roles_up_to_level(level: int) -> list[str]:
    if level <= 1:
        return ["OPERATOR"]
    if level == 2:
        return ["OPERATOR", "MANAGER"]
    return ["OPERATOR", "MANAGER", "ADMIN"]


def get_recipients_for_level(level: int) -> list[User]:
    """CUMULATIVE recipients by level (OPERATOR -> OP+MANAGER -> OP+MANAGER+ADMIN)."""
    roles = _roles_up_to_level(level)

    users = User.objects.none()
    for r in roles:
        users = users.union(_users_for_role_exact(r))

    recipients: list[User] = []
    for u in users:
        profile, _ = UserProfile.objects.get_or_create(user=u)
        if profile.status == UserProfile.STATUS_ACTIVE and u.email:
            recipients.append(u)

    # dedupe + stable order
    recipients = sorted({u.id: u for u in recipients}.values(), key=lambda x: x.id)
    return recipients


def get_recipients_for_role_exact(role: str) -> list[User]:
    """EXACT role recipients (used by simulation)."""
    users_qs = _users_for_role_exact(role)

    recipients: list[User] = []
    for u in users_qs:
        profile, _ = UserProfile.objects.get_or_create(user=u)
        if profile.status == UserProfile.STATUS_ACTIVE and u.email:
            recipients.append(u)

    recipients = sorted({u.id: u for u in recipients}.values(), key=lambda x: x.id)
    return recipients


# ------------------------------------------------------------
# Alert creation/update (1 OPEN alert per sensor)
# ------------------------------------------------------------

def get_or_create_open_alert_for_sensor(sensor: Sensor, reading: Reading) -> Alert | None:
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
        alert.updated_at = timezone.now()
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
        next_retry_at=now,
        last_notified_at=None,
    )


# ------------------------------------------------------------
# Professional email (HTML + text fallback) with buttons
# ------------------------------------------------------------

def _app_base_url() -> str:
    """
    Base URL for clickable buttons.
    Set in settings:
      APP_BASE_URL = "http://127.0.0.1:8000"
    """
    base = getattr(settings, "APP_BASE_URL", "").rstrip("/")
    if not base:
        # Safe fallback (still works if you open locally)
        base = "http://127.0.0.1:8000"
    return base


def _build_action_urls(alert: Alert) -> dict:
    base = _app_base_url()
    return {
        "ack": f"{base}/api/alerts/{alert.id}/ack/",
        "resolve": f"{base}/api/alerts/{alert.id}/resolve/",
        # Optional: link to UI details if you have it
        "details": f"{base}/dashboard/alerts/{alert.id}",
    }


def build_email_for_role(alert: Alert, *, role: str, seq: int) -> Tuple[str, str, str]:
    """
    Returns (subject, text_message, html_message)
    """
    cfg = get_monitoring_config()
    urls = _build_action_urls(alert)

    subject = f"⚠️ [{role}] Cold Chain Alert #{alert.id} • {alert.sensor.name} • {alert.severity} • Level {alert.level}"

    role_title = {
        "OPERATOR": "Operator Action Required",
        "MANAGER": "Manager Escalation Notice",
        "ADMIN": "Admin Critical Escalation",
    }.get(role, "Action Required")

    role_instructions = {
        "OPERATOR": "Check the sensor and fridge immediately. If you take ownership, acknowledge the alert.",
        "MANAGER": "Coordinate with the operator and decide next actions. Acknowledge if handled to stop escalation.",
        "ADMIN": "Critical escalation. Dispatch an intervention and track until resolution. Acknowledge immediately if assigned.",
    }.get(role, "Please acknowledge in the web app to stop escalation.")

    # ---- Plain text (fallback)
    text_message = (
        f"{role_title}\n"
        f"----------------------------------------\n"
        f"Alert #{alert.id} | Sensor: {alert.sensor.name}\n"
        f"Severity: {alert.severity}\n"
        f"System Level: {alert.level}\n"
        f"Temperature: {alert.temperature}\n"
        f"Humidity: {alert.humidity}\n"
        f"Thresholds: {cfg['tempMin']} .. {cfg['tempMax']}\n"
        f"Status: {alert.status}\n"
        f"Created: {alert.created_at}\n\n"
        f"Instructions: {role_instructions}\n\n"
        f"Acknowledge (ACK): {urls['ack']}\n"
        f"Resolve: {urls['resolve']}\n"
        f"Details: {urls['details']}\n"
        f"\nEmail sequence: {seq}\n"
    )

    # ---- HTML (with buttons)
    # NOTE: email clients don't support <button> well, use <a> styled as a button.
    html_message = f"""
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f6f8fb;font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f6f8fb;padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" cellpadding="0" cellspacing="0" width="640" style="background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e7ecf3;">
            <tr>
              <td style="padding:18px 22px;background:#0b1220;color:#ffffff;">
                <div style="font-size:14px;opacity:.9;">{role_title}</div>
                <div style="font-size:20px;font-weight:700;margin-top:4px;">
                  ⚠️ Cold Chain Alert #{alert.id}
                </div>
                <div style="font-size:13px;opacity:.9;margin-top:6px;">
                  Sensor: <b>{alert.sensor.name}</b> • Severity: <b>{alert.severity}</b> • Level: <b>{alert.level}</b>
                </div>
              </td>
            </tr>

            <tr>
              <td style="padding:18px 22px;">
                <p style="margin:0 0 12px 0;color:#1f2937;font-size:14px;line-height:1.5;">
                  <b>Instructions:</b> {role_instructions}
                </p>

                <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border:1px solid #e7ecf3;border-radius:10px;">
                  <tr>
                    <td style="padding:12px 14px;">
                      <div style="font-size:12px;color:#64748b;margin-bottom:6px;">Current reading</div>
                      <div style="font-size:14px;color:#0f172a;">
                        <b>Temperature:</b> {alert.temperature} °C &nbsp; | &nbsp;
                        <b>Humidity:</b> {alert.humidity} %
                      </div>
                      <div style="font-size:13px;color:#334155;margin-top:8px;">
                        <b>Thresholds:</b> {cfg['tempMin']} .. {cfg['tempMax']} &nbsp; | &nbsp;
                        <b>Status:</b> {alert.status}
                      </div>
                      <div style="font-size:12px;color:#64748b;margin-top:8px;">
                        Created: {alert.created_at} &nbsp; | &nbsp; Email sequence: {seq}
                      </div>
                    </td>
                  </tr>
                </table>

                <div style="margin-top:16px;">
                  <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;">
                    <tr>
                      <td style="padding-right:10px;">
                        <a href="{urls['ack']}"
                           style="display:inline-block;background:#16a34a;color:#ffffff;text-decoration:none;font-weight:700;
                                  padding:12px 16px;border-radius:10px;font-size:14px;">
                          ✅ Acknowledge (ACK)
                        </a>
                      </td>
                      <td style="padding-right:10px;">
                        <a href="{urls['resolve']}"
                           style="display:inline-block;background:#0ea5e9;color:#ffffff;text-decoration:none;font-weight:700;
                                  padding:12px 16px;border-radius:10px;font-size:14px;">
                          🧰 Resolve
                        </a>
                      </td>
                      <td>
                        <a href="{urls['details']}"
                           style="display:inline-block;background:#111827;color:#ffffff;text-decoration:none;font-weight:700;
                                  padding:12px 16px;border-radius:10px;font-size:14px;">
                          🔎 View details
                        </a>
                      </td>
                    </tr>
                  </table>
                </div>

                <p style="margin:16px 0 0 0;color:#64748b;font-size:12px;line-height:1.5;">
                  If the buttons don’t work, copy/paste these links:<br/>
                  ACK: <a href="{urls['ack']}" style="color:#0ea5e9;">{urls['ack']}</a><br/>
                  Resolve: <a href="{urls['resolve']}" style="color:#0ea5e9;">{urls['resolve']}</a><br/>
                  Details: <a href="{urls['details']}" style="color:#0ea5e9;">{urls['details']}</a>
                </p>
              </td>
            </tr>

            <tr>
              <td style="padding:14px 22px;background:#f8fafc;border-top:1px solid #e7ecf3;color:#64748b;font-size:12px;">
                This alert was generated automatically by the monitoring system.
              </td>
            </tr>
          </table>
          <div style="font-size:11px;color:#94a3b8;margin-top:10px;">
            Cold Chain Monitoring • Automated Notification
          </div>
        </td>
      </tr>
    </table>
  </body>
</html>
""".strip()

    return subject, text_message, html_message


def send_role_email(alert: Alert, *, role: str, seq: int, recipients: list[User]) -> tuple[bool, str, list[str]]:
    if not recipients:
        return False, f"No email recipients for role {role}.", []

    subject, text_message, html_message = build_email_for_role(alert, role=role, seq=seq)
    emails = [u.email for u in recipients if u.email]
    emails = sorted(set(emails))  # dedupe by email

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
    if not from_email:
        return False, "DEFAULT_FROM_EMAIL is not configured in settings.py", emails

    try:
        send_mail(
            subject=subject,
            message=text_message,          # plain text
            from_email=from_email,
            recipient_list=emails,
            fail_silently=False,
            html_message=html_message,     # HTML with buttons
        )
        return True, "", emails
    except Exception as e:
        return False, str(e), emails


# ------------------------------------------------------------
# Ticket
# ------------------------------------------------------------

def ensure_ticket(alert: Alert) -> Ticket:
    ticket = Ticket.objects.filter(alert=alert).first()
    if ticket:
        return ticket

    title = f"Auto ticket: {alert.sensor.name} (Alert #{alert.id})"
    description = "Auto-created by monitoring escalation."
    priority = Ticket.PRIORITY_HIGH if alert.severity == Alert.SEV_HIGH else Ticket.PRIORITY_MEDIUM

    return Ticket.objects.create(
        alert=alert,
        title=title,
        description=description,
        priority=priority,
        status=Ticket.STATUS_OPEN,
    )


# ------------------------------------------------------------
# Logging (your model uses sent_at)
# ------------------------------------------------------------

def log_email_notification(alert: Alert, *, recipients_joined: str, attempt_number: int, ok: bool, err: str) -> None:
    AlertNotificationLog.objects.create(
        alert=alert,
        channel=AlertNotificationLog.CHANNEL_EMAIL,
        recipients=recipients_joined,
        attempt_number=attempt_number,
        sent_at=timezone.now(),
        status=AlertNotificationLog.STATUS_SENT if ok else AlertNotificationLog.STATUS_FAILED,
        error=err or "",
    )


# ------------------------------------------------------------
# OPTIONAL: Email-only processor (if you still use it elsewhere)
# ------------------------------------------------------------

def process_due_alert_email_only(alert: Alert) -> None:
    """
    Email-only escalation engine (optional).
    Uses cumulative recipients (level-based).
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

    attempt_number = min(alert.tries_without_response + 1, escalation_count)

    # Recipients (cumulative)
    recipients = get_recipients_for_level(alert.level)

    # Role label for email content (based on level)
    role = "OPERATOR" if alert.level == 1 else ("MANAGER" if alert.level == 2 else "ADMIN")

    ok, err, emails = send_role_email(alert, role=role, seq=attempt_number, recipients=recipients)
    log_email_notification(
        alert,
        recipients_joined=",".join(emails),
        attempt_number=attempt_number,
        ok=ok,
        err=err,
    )

    alert.last_notified_at = now
    alert.tries_without_response = min(alert.tries_without_response + 1, escalation_count)

    if alert.tries_without_response >= escalation_count:
        if alert.level < 3:
            alert.level += 1
            alert.tries_without_response = 0
            alert.next_retry_at = now  # immediate notify at new level
            if alert.level == 3:
                ensure_ticket(alert)
        else:
            alert.next_retry_at = now + timedelta(minutes=repeat_delay_min)
    else:
        alert.next_retry_at = now + timedelta(minutes=retry_delay_min)

    alert.updated_at = now
    alert.save(update_fields=["tries_without_response", "level", "last_notified_at", "next_retry_at", "updated_at"])
