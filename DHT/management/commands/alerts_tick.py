from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from DHT.models import Alert
from DHT.alerts_services import process_due_alert  # adapte si ton module est "alert_services"


class Command(BaseCommand):
    help = "Process due OPEN alerts (email + call + escalation + ticket creation)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200, help="Max alerts per run.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force processing even if next_retry_at is in the future (testing only).",
        )

    def handle(self, *args, **options):
        limit: int = options["limit"]
        force: bool = options["force"]

        now = timezone.now()

        # Due filter
        filt = Q(status=Alert.STATUS_OPEN)
        if not force:
            filt &= (Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))

        # Small batch
        alerts = (
            Alert.objects.select_related("sensor")
            .filter(filt)
            .order_by("next_retry_at", "id")[:limit]
        )

        processed = 0
        skipped = 0
        errors = 0

        for a in alerts:
            try:
                # Lock row to avoid double processing if scheduler runs twice
                with transaction.atomic():
                    locked = (
                        Alert.objects.select_for_update()
                        .select_related("sensor")
                        .get(pk=a.pk)
                    )

                    # Re-check due inside lock
                    if locked.status != Alert.STATUS_OPEN:
                        skipped += 1
                        continue
                    if not force and locked.next_retry_at and locked.next_retry_at > now:
                        skipped += 1
                        continue

                    before = (locked.level, locked.tries_without_response, locked.next_retry_at)

                    process_due_alert(locked)

                    locked.refresh_from_db()
                    after = (locked.level, locked.tries_without_response, locked.next_retry_at)

                    processed += 1
                    self.stdout.write(
                        f"[OK] alert#{locked.id} "
                        f"level {before[0]}->{after[0]} tries {before[1]}->{after[1]} "
                        f"next_retry_at {before[2]}->{after[2]} status={locked.status}"
                    )
            except Alert.DoesNotExist:
                skipped += 1
            except Exception as e:
                errors += 1
                self.stderr.write(f"[ERR] alert#{a.id}: {e}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. processed={processed} skipped={skipped} errors={errors} time={now.isoformat()}"
        ))
