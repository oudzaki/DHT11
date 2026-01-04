from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from DHT.models import (
    Sensor,
    Reading,
    Alert,
    Ticket,
    UserProfile,
    AlertNotificationLog,
)
from DHT.alerts_services import (
    get_or_create_open_alert_for_sensor,
    process_due_alert,
    get_monitoring_config,
)


class Command(BaseCommand):
    """
    Scenario exact:
      - Level 1: 3 notifications cycles -> OPERATOR
      - Level 2: 3 notification cycles -> OPERATOR + MANAGER (cumulative)
      - Level 3: 3 notification cycles -> OPERATOR + MANAGER + ADMIN (cumulative)
      - Ticket created when reaching level 3
      - Then test ACK and RESOLVE (stop notifications)

    Usage:
      python manage.py simulate_incident --reset --force-due --temp 15 --after both
    """

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Clean simulation data.")
        parser.add_argument("--sensor-name", type=str, default="SENSOR_TEST_001")
        parser.add_argument("--temp", type=float, default=15.0)
        parser.add_argument("--hum", type=float, default=60.0)
        parser.add_argument("--force-due", action="store_true", help="Force next_retry_at in the past each tick.")

        parser.add_argument(
            "--after",
            choices=["none", "ack", "resolve", "both"],
            default="both",
            help="After escalation scenario, test ACK/RESOLVE.",
        )
        parser.add_argument("--ack-user", choices=["operator", "manager", "admin"], default="operator")
        parser.add_argument("--resolve-user", choices=["operator", "manager", "admin"], default="manager")

        parser.add_argument(
            "--expect-escalation-count",
            type=int,
            default=3,
            help="Expected ESCALATION_COUNT (for validation output).",
        )

    def handle(self, *args, **opts):
        reset: bool = opts["reset"]
        sensor_name: str = opts["sensor_name"]
        temp: float = opts["temp"]
        hum: float = opts["hum"]
        force_due: bool = opts["force_due"]
        after: str = opts["after"]
        ack_user: str = opts["ack_user"]
        resolve_user: str = opts["resolve_user"]
        expected_escalation_count: int = opts["expect_escalation_count"]

        cfg = get_monitoring_config()
        escalation_count = int(cfg["escalationCount"])

        self.stdout.write(f"Monitoring config: {cfg}")
        if escalation_count != expected_escalation_count:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️ escalationCount runtime={escalation_count} but expected={expected_escalation_count}. "
                    f"Your scenario '3 times each level' assumes 3."
                )
            )

        if reset:
            self._reset(sensor_name)

        # 1) Users (roles from flags)
        operator = self._ensure_user(
            username="test-operator",
            email="tahahat4@gmail.com",
            is_staff=False,
            is_superuser=False,
            phone="212624363823",
        )
        manager = self._ensure_user(
            username="test-manager",
            email="tahaprogame3@gmail.com",
            is_staff=True,
            is_superuser=False,
            phone="212671832733",
        )
        admin = self._ensure_user(
            username="test-admin",
            email="hathout.moahmmedtaha@gmail.com",
            is_staff=False,
            is_superuser=True,
            phone="212663222948",
        )

        ack_by = {"operator": operator, "manager": manager, "admin": admin}[ack_user]
        resolve_by = {"operator": operator, "manager": manager, "admin": admin}[resolve_user]

        # 2) Sensor
        sensor, _ = Sensor.objects.get_or_create(name=sensor_name)

        # 3) Reading out-of-range
        reading = Reading.objects.create(sensor=sensor, temperature=temp, humidity=hum)

        # 4) Create or update alert (OPEN)
        alert = get_or_create_open_alert_for_sensor(sensor, reading)
        if not alert:
            raise RuntimeError(
                f"No alert created. Temp={temp} might be in range. "
                f"Increase --temp or adjust TEMP_MIN/TEMP_MAX."
            )

        # Put alert into clean deterministic state
        alert.status = Alert.STATUS_OPEN
        alert.level = 1
        alert.tries_without_response = 0
        alert.next_retry_at = timezone.now() - timedelta(seconds=2)
        alert.save(update_fields=["status", "level", "tries_without_response", "next_retry_at"])

        self.stdout.write(self.style.SUCCESS(f"Alert ready: id={alert.id} status={alert.status} level={alert.level}"))

        # ---------------------------------------------------------
        # Scenario A: No response (3 cycles per level)
        # ---------------------------------------------------------
        self.stdout.write("\n==== Scenario A: NO RESPONSE (3/3/3 escalation) ====")
        self._run_phase(alert.id, level=1, times=escalation_count, force_due=force_due)
        self._run_phase(alert.id, level=2, times=escalation_count, force_due=force_due)
        self._run_phase(alert.id, level=3, times=escalation_count, force_due=force_due)

        alert.refresh_from_db()

        # Ticket check (OneToOne)
        self.stdout.write("\n---- Ticket check ----")
        ticket = Ticket.objects.filter(alert_id=alert.id).first()
        if ticket:
            self.stdout.write(self.style.SUCCESS(f"✅ Ticket exists: id={ticket.id} status={ticket.status} priority={ticket.priority}"))
        else:
            self.stdout.write(self.style.ERROR("❌ Ticket NOT created. Check ensure_ticket_for_level3() call when reaching level 3."))

        self._print_logs_summary(alert.id)
        self._print_last_recipients(alert.id)

        # ---------------------------------------------------------
        # Scenario B: ACK stop
        # ---------------------------------------------------------
        if after in ("ack", "both"):
            self.stdout.write("\n==== Scenario B: ACK stops notifications ====")
            self._apply_ack(alert.id, ack_by)
            self._assert_no_new_logs(alert.id, force_due=force_due)

        # ---------------------------------------------------------
        # Scenario C: RESOLVE stop
        # ---------------------------------------------------------
        if after in ("resolve", "both"):
            self.stdout.write("\n==== Scenario C: RESOLVE stops notifications ====")
            # Re-open so we can test resolve cleanly
            alert.refresh_from_db()
            alert.status = Alert.STATUS_OPEN
            alert.level = 1
            alert.tries_without_response = 0
            alert.next_retry_at = timezone.now() - timedelta(seconds=2)
            alert.save(update_fields=["status", "level", "tries_without_response", "next_retry_at"])

            # Prove it notifies again when OPEN
            self._tick(alert.id, label="Before RESOLVE tick (should notify)", force_due=force_due)

            self._apply_resolve(alert.id, resolve_by)
            self._assert_no_new_logs(alert.id, force_due=force_due)

        self.stdout.write(self.style.SUCCESS("\n✅ DONE"))

    # ---------------------------------------------------------
    # Phase runner
    # ---------------------------------------------------------

    def _run_phase(self, alert_id: int, *, level: int, times: int, force_due: bool) -> None:
        self.stdout.write(f"\n---- Level {level}: {times} notification cycles ----")
        for i in range(1, times + 1):
            self._tick(alert_id, label=f"Level {level} tick #{i}", force_due=force_due)

        self._print_last_recipients(alert_id)

    def _tick(self, alert_id: int, *, label: str, force_due: bool) -> None:
        before = AlertNotificationLog.objects.filter(alert_id=alert_id).count()
        now = timezone.now()

        with transaction.atomic():
            alert = Alert.objects.select_for_update().get(pk=alert_id)

            # Force due so you don't wait minutes
            if force_due and alert.status == Alert.STATUS_OPEN:
                alert.next_retry_at = now - timedelta(seconds=2)
                alert.save(update_fields=["next_retry_at"])

            process_due_alert(alert)

        after = AlertNotificationLog.objects.filter(alert_id=alert_id).count()
        state = Alert.objects.get(pk=alert_id)
        self.stdout.write(
            f"[TICK] {label} | logs {before}->{after} | "
            f"status={state.status} level={state.level} tries={state.tries_without_response} next_retry_at={state.next_retry_at}"
        )

    # ---------------------------------------------------------
    # Stop actions
    # ---------------------------------------------------------

    def _apply_ack(self, alert_id: int, user: User) -> None:
        alert = Alert.objects.get(pk=alert_id)
        now = timezone.now()

        if alert.status != Alert.STATUS_OPEN:
            self.stdout.write(self.style.WARNING(f"ACK: alert not OPEN (status={alert.status}). Setting OPEN for test."))
            alert.status = Alert.STATUS_OPEN

        alert.status = Alert.STATUS_ACK
        alert.acked_by = user
        alert.acked_at = now

        alert.next_retry_at = None
        alert.tries_without_response = 0

        alert.save(update_fields=["status", "acked_by", "acked_at", "next_retry_at", "tries_without_response"])
        self.stdout.write(self.style.SUCCESS(f"✅ ACK applied by {user.username}: alert#{alert.id} status={alert.status}"))

    def _apply_resolve(self, alert_id: int, user: User) -> None:
        alert = Alert.objects.get(pk=alert_id)
        now = timezone.now()

        alert.status = Alert.STATUS_RESOLVED
        alert.resolved_by = user
        alert.resolved_at = now

        alert.next_retry_at = None
        alert.tries_without_response = 0

        alert.save(update_fields=["status", "resolved_by", "resolved_at", "next_retry_at", "tries_without_response"])
        self.stdout.write(self.style.SUCCESS(f"✅ RESOLVE applied by {user.username}: alert#{alert.id} status={alert.status}"))

    def _assert_no_new_logs(self, alert_id: int, *, force_due: bool) -> None:
        before = AlertNotificationLog.objects.filter(alert_id=alert_id).count()
        self._tick(alert_id, label="Post-stop tick (should NOT notify)", force_due=force_due)
        after = AlertNotificationLog.objects.filter(alert_id=alert_id).count()

        if after == before:
            self.stdout.write(self.style.SUCCESS(f"✅ OK: No new logs after stop. logs={before}"))
        else:
            self.stdout.write(self.style.ERROR(f"❌ FAIL: Logs increased after stop: {before}->{after}"))

    # ---------------------------------------------------------
    # Reporting
    # ---------------------------------------------------------

    def _print_logs_summary(self, alert_id: int) -> None:
        total = AlertNotificationLog.objects.filter(alert_id=alert_id).count()
        email_total = AlertNotificationLog.objects.filter(alert_id=alert_id, channel=AlertNotificationLog.CHANNEL_EMAIL).count()
        call_total = AlertNotificationLog.objects.filter(alert_id=alert_id, channel=AlertNotificationLog.CHANNEL_CALL).count()

        self.stdout.write("\n---- Logs summary ----")
        self.stdout.write(f"total={total}, email={email_total}, call={call_total}")

    def _print_last_recipients(self, alert_id: int) -> None:
        last_email = (
            AlertNotificationLog.objects
            .filter(alert_id=alert_id, channel=AlertNotificationLog.CHANNEL_EMAIL)
            .order_by("-id")
            .first()
        )
        last_call = (
            AlertNotificationLog.objects
            .filter(alert_id=alert_id, channel=AlertNotificationLog.CHANNEL_CALL)
            .order_by("-id")
            .first()
        )

        self.stdout.write("---- Last recipients ----")
        if last_email:
            self.stdout.write(f"EMAIL: attempt={last_email.attempt_number} status={last_email.status} recipients={last_email.recipients}")
        else:
            self.stdout.write("EMAIL: none")

        if last_call:
            self.stdout.write(f"CALL : attempt={last_call.attempt_number} status={last_call.status} recipients={last_call.recipients}")
        else:
            self.stdout.write("CALL : none")

    # ---------------------------------------------------------
    # Setup helpers
    # ---------------------------------------------------------

    def _ensure_user(self, username: str, email: str, *, is_staff: bool, is_superuser: bool, phone: str) -> User:
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
        profile.phone = phone
        profile.save()

        return u

    def _reset(self, sensor_name: str) -> None:
        AlertNotificationLog.objects.filter(alert__sensor__name=sensor_name).delete()
        Ticket.objects.filter(alert__sensor__name=sensor_name).delete()
        Alert.objects.filter(sensor__name=sensor_name).delete()
        Reading.objects.filter(sensor__name=sensor_name).delete()
        Sensor.objects.filter(name=sensor_name).delete()
        self.stdout.write(self.style.WARNING("Reset done for this sensor scope."))
