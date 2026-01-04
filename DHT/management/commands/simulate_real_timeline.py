from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

from DHT.models import Sensor, Reading, Alert, Ticket, UserProfile, AlertNotificationLog
from DHT.alerts_services import (
    get_or_create_open_alert_for_sensor,
    get_recipients_for_role_exact,
    send_role_email,
    log_email_notification,
    ensure_ticket,
)


@dataclass(frozen=True)
class Step:
    label: str
    wait_before_seconds: int
    send_operator_seq: int | None = None
    send_manager_seq: int | None = None
    send_admin_seq: int | None = None
    # alert state change simulation
    set_level: int | None = None
    set_tries: int | None = None


class Command(BaseCommand):
    """
    Real timeline simulation (2 min spacing) exactly as requested.

    Timeline:
      t0  : OPERATOR #1
      t+2 : OPERATOR #2
      t+4 : OPERATOR #3 + MANAGER #1 (same instant)  -> level becomes 2
      t+6 : OPERATOR #4 + MANAGER #2
      t+8 : OPERATOR #5 + MANAGER #3 + ADMIN #1 (same instant) -> level becomes 3
      t+10: OPERATOR #6 + MANAGER #4 + ADMIN #2
      t+12: OPERATOR #7 + MANAGER #5 + ADMIN #3
      then create ticket
      then simulate ACK by a user and assign ticket to him
      then RESOLVE
    """

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--sensor-name", type=str, default="SENSOR_TIMELINE_001")
        parser.add_argument("--temp", type=float, default=15.0)
        parser.add_argument("--hum", type=float, default=60.0)

        parser.add_argument(
            "--sleep-seconds",
            type=int,
            default=120,
            help="Seconds between steps (use 120 for real 2min). For quick test you can set 5.",
        )

        parser.add_argument(
            "--ack-user",
            choices=["operator", "manager", "admin"],
            default="operator",
        )

    def handle(self, *args, **opts):
        reset: bool = opts["reset"]
        sensor_name: str = opts["sensor_name"]
        temp: float = opts["temp"]
        hum: float = opts["hum"]
        sleep_seconds: int = opts["sleep_seconds"]
        ack_user_choice: str = opts["ack_user"]

        if reset:
            self._reset(sensor_name)

        # Ensure users exist (so we have recipients)
        operator = self._ensure_user("test-operator", "tahahat4@gmail.com", is_staff=False, is_superuser=False)
        manager = self._ensure_user("test-manager", "tahaprogame3@gmail.com", is_staff=True, is_superuser=False)
        admin = self._ensure_user("test-admin", "hathout.mohammedtaha@gmail.com", is_staff=False, is_superuser=True)

        ack_user = {"operator": operator, "manager": manager, "admin": admin}[ack_user_choice]

        # Sensor + reading + alert
        sensor, _ = Sensor.objects.get_or_create(name=sensor_name)
        reading = Reading.objects.create(sensor=sensor, temperature=temp, humidity=hum)

        alert = get_or_create_open_alert_for_sensor(sensor, reading)
        if not alert:
            raise RuntimeError("No alert created. Make temp out of range or adjust thresholds.")

        # start state
        alert.status = Alert.STATUS_OPEN
        alert.level = 1
        alert.tries_without_response = 0
        alert.next_retry_at = timezone.now()
        alert.save(update_fields=["status", "level", "tries_without_response", "next_retry_at"])

        self.stdout.write(self.style.SUCCESS(f"Alert created: id={alert.id} L{alert.level} status={alert.status}"))

        steps = [
            Step(label="t0: OPERATOR #1", wait_before_seconds=0, send_operator_seq=1, set_level=1, set_tries=1),
            Step(label="t+2: OPERATOR #2", wait_before_seconds=sleep_seconds, send_operator_seq=2, set_level=1, set_tries=2),
            Step(label="t+4: OPERATOR #3 + MANAGER #1 (escalate->L2)", wait_before_seconds=sleep_seconds, send_operator_seq=3, send_manager_seq=1, set_level=2, set_tries=1),
            Step(label="t+6: OPERATOR #4 + MANAGER #2", wait_before_seconds=sleep_seconds, send_operator_seq=4, send_manager_seq=2, set_level=2, set_tries=2),
            Step(label="t+8: OPERATOR #5 + MANAGER #3 + ADMIN #1 (escalate->L3)", wait_before_seconds=sleep_seconds, send_operator_seq=5, send_manager_seq=3, send_admin_seq=1, set_level=3, set_tries=1),
            Step(label="t+10: OPERATOR #6 + MANAGER #4 + ADMIN #2", wait_before_seconds=sleep_seconds, send_operator_seq=6, send_manager_seq=4, send_admin_seq=2, set_level=3, set_tries=2),
            Step(label="t+12: OPERATOR #7 + MANAGER #5 + ADMIN #3", wait_before_seconds=sleep_seconds, send_operator_seq=7, send_manager_seq=5, send_admin_seq=3, set_level=3, set_tries=3),
        ]

        for s in steps:
            if s.wait_before_seconds > 0:
                self.stdout.write(f"\n⏳ Waiting {s.wait_before_seconds} seconds...")
                time.sleep(s.wait_before_seconds)

            alert.refresh_from_db()
            if alert.status != Alert.STATUS_OPEN:
                self.stdout.write(self.style.WARNING(f"Alert is not OPEN anymore (status={alert.status}). Stopping timeline."))
                return

            # Apply simulated state change (for realism)
            if s.set_level is not None:
                alert.level = s.set_level
            if s.set_tries is not None:
                alert.tries_without_response = s.set_tries

            alert.last_notified_at = timezone.now()
            alert.next_retry_at = timezone.now() + timedelta(seconds=sleep_seconds)  # next expected
            alert.save(update_fields=["level", "tries_without_response", "last_notified_at", "next_retry_at"])

            self.stdout.write(self.style.SUCCESS(f"\n[STEP] {s.label} | Alert state: L{alert.level} tries={alert.tries_without_response}"))

            # Send emails "same instant" in this step (no extra sleep between)
            self._send_role_if_needed(alert, role="OPERATOR", seq=s.send_operator_seq)
            self._send_role_if_needed(alert, role="MANAGER", seq=s.send_manager_seq)
            self._send_role_if_needed(alert, role="ADMIN", seq=s.send_admin_seq)

        # After last step: create ticket
        alert.refresh_from_db()
        self.stdout.write("\n---- Creating ticket ----")
        ticket = ensure_ticket(alert)
        self.stdout.write(self.style.SUCCESS(f"✅ Ticket created: id={ticket.id} status={ticket.status}"))

        # Simulate ACK + assign ticket
        self.stdout.write("\n---- Simulate ACK + assign ticket ----")
        self._apply_ack_and_assign(alert, ticket, ack_user)

        # Simulate RESOLVE
        self.stdout.write("\n---- Simulate RESOLVE ----")
        self._apply_resolve(alert, ticket, ack_user)

        self.stdout.write(self.style.SUCCESS("\n✅ Real timeline simulation finished."))

    # ----------------------------
    # Email sending
    # ----------------------------

    def _send_role_if_needed(self, alert: Alert, *, role: str, seq: int | None) -> None:
        if seq is None:
            return

        recipients = get_recipients_for_role_exact(role)
        ok, err, emails = send_role_email(alert, role=role, seq=seq, recipients=recipients)

        # attempt_number can store seq (even if doc says 1..3, no DB constraint)
        log_email_notification(
            alert,
            recipients_joined=",".join(emails),
            attempt_number=seq,
            ok=ok,
            err=err,
        )

        if ok:
            self.stdout.write(f"📧 Sent {role} email #{seq} -> {emails}")
        else:
            self.stdout.write(self.style.ERROR(f"❌ Failed {role} email #{seq}: {err} | recipients={emails}"))

    # ----------------------------
    # ACK / RESOLVE simulation
    # ----------------------------

    def _apply_ack_and_assign(self, alert: Alert, ticket: Ticket, user: User) -> None:
        now = timezone.now()
        alert.refresh_from_db()

        alert.status = Alert.STATUS_ACK
        alert.acked_by = user
        alert.acked_at = now
        alert.next_retry_at = None
        alert.save(update_fields=["status", "acked_by", "acked_at", "next_retry_at"])

        ticket.refresh_from_db()
        ticket.assigned_to = user
        ticket.status = Ticket.STATUS_IN_PROGRESS
        ticket.save(update_fields=["assigned_to", "status"])

        self.stdout.write(self.style.SUCCESS(f"✅ Alert ACK by {user.username}, ticket assigned and IN_PROGRESS."))

    def _apply_resolve(self, alert: Alert, ticket: Ticket, user: User) -> None:
        now = timezone.now()
        alert.refresh_from_db()

        alert.status = Alert.STATUS_RESOLVED
        alert.resolved_by = user
        alert.resolved_at = now
        alert.next_retry_at = None
        alert.save(update_fields=["status", "resolved_by", "resolved_at", "next_retry_at"])

        ticket.refresh_from_db()
        ticket.status = Ticket.STATUS_CLOSED
        ticket.closed_at = now
        ticket.save(update_fields=["status", "closed_at"])

        self.stdout.write(self.style.SUCCESS("✅ Alert RESOLVED and ticket CLOSED."))

    # ----------------------------
    # Setup / reset
    # ----------------------------

    def _ensure_user(self, username: str, email: str, *, is_staff: bool, is_superuser: bool) -> User:
        u, created = User.objects.get_or_create(username=username, defaults={"email": email})
        if created:
            u.set_password("test12345")
        u.email = email
        u.is_staff = is_staff
        u.is_superuser = is_superuser
        u.is_active = True
        u.save()

        profile, _ = UserProfile.objects.get_or_create(user=u)
        profile.status = UserProfile.STATUS_ACTIVE
        profile.save()

        return u

    def _reset(self, sensor_name: str) -> None:
        AlertNotificationLog.objects.filter(alert__sensor__name=sensor_name).delete()
        Ticket.objects.filter(alert__sensor__name=sensor_name).delete()
        Alert.objects.filter(sensor__name=sensor_name).delete()
        Reading.objects.filter(sensor__name=sensor_name).delete()
        Sensor.objects.filter(name=sensor_name).delete()
        self.stdout.write(self.style.WARNING("Reset done for this sensor scope."))
