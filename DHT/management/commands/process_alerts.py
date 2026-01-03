from django.core.management.base import BaseCommand
from django.utils import timezone

from DHT.models import Alert
from DHT.alerts_services import process_due_alert


class Command(BaseCommand):
    help = "Process due alerts: send notifications, retry, escalate."

    def handle(self, *args, **options):
        now = timezone.now()
        due_alerts = Alert.objects.filter(status=Alert.STATUS_OPEN).filter(next_retry_at__isnull=False).order_by("next_retry_at")

        processed = 0
        for alert in due_alerts:
            if alert.next_retry_at and alert.next_retry_at <= now:
                process_due_alert(alert)
                processed += 1

        self.stdout.write(self.style.SUCCESS(f"Processed {processed} due alerts."))
