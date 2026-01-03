from django.core.management.base import BaseCommand
from django.utils import timezone

from DHT.models import Alert
from DHT.alerts_services import process_due_alert


class Command(BaseCommand):
    help = "Process due alerts: send notifications, retry and escalate."

    def handle(self, *args, **options):
        now = timezone.now()

        # Only OPEN alerts that are due for processing
        due_alerts = (
            Alert.objects
            .filter(
                status=Alert.STATUS_OPEN,
                next_retry_at__isnull=False,
                next_retry_at__lte=now,
            )
            .order_by("next_retry_at")
        )

        processed = 0

        for alert in due_alerts:
            process_due_alert(alert)
            processed += 1

        self.stdout.write(
            self.style.SUCCESS(f"Processed {processed} due alert(s).")
        )
# python manage.py process_alerts