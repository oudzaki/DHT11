from datetime import datetime
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Alert
from .alerts_serializers import AlertSerializer, AlertDetailSerializer
from .alerts_services import get_monitoring_config


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Endpoints:
    - GET    /api/alerts/
    - GET    /api/alerts/{id}/
    - POST   /api/alerts/{id}/ack/
    - POST   /api/alerts/{id}/resolve/
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Alert.objects.select_related("sensor").order_by("-created_at")

    def get_serializer_class(self):
        return AlertDetailSerializer if self.action == "retrieve" else AlertSerializer

    # --------------------------------------------------
    # LIST WITH FILTERS
    # --------------------------------------------------
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()

        sensor_id = request.query_params.get("sensor_id")
        status_q = request.query_params.get("status")
        severity = request.query_params.get("severity")

        if sensor_id:
            qs = qs.filter(sensor_id=sensor_id)

        if status_q:
            qs = qs.filter(status=status_q)

        if severity:
            qs = qs.filter(severity=severity)

        # -------- Date filtering (date_from / date_to)
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        if date_from:
            dt = self._parse_to_aware_datetime(date_from, start_of_day=True)
            if dt:
                qs = qs.filter(created_at__gte=dt)

        if date_to:
            dt = self._parse_to_aware_datetime(date_to, start_of_day=False)
            if dt:
                qs = qs.filter(created_at__lte=dt)

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    # --------------------------------------------------
    # ACTIONS
    # --------------------------------------------------
    @action(detail=True, methods=["POST"])
    def ack(self, request, pk=None):
        alert = self.get_object()

        if alert.status != Alert.STATUS_OPEN:
            return Response(
                {"detail": "Only OPEN alerts can be acknowledged."},
                status=status.HTTP_409_CONFLICT,
            )

        alert.status = Alert.STATUS_ACK
        alert.acked_by = request.user
        alert.acked_at = timezone.now()
        alert.next_retry_at = None  # stop escalation

        alert.save(update_fields=[
            "status",
            "acked_by",
            "acked_at",
            "next_retry_at",
            "updated_at",
        ])

        return Response({"status": "ACKNOWLEDGED"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST"])
    def resolve(self, request, pk=None):
        alert = self.get_object()

        if alert.status == Alert.STATUS_RESOLVED:
            return Response(
                {"detail": "Alert already resolved."},
                status=status.HTTP_409_CONFLICT,
            )

        alert.status = Alert.STATUS_RESOLVED
        alert.resolved_by = request.user
        alert.resolved_at = timezone.now()
        alert.next_retry_at = None

        alert.save(update_fields=[
            "status",
            "resolved_by",
            "resolved_at",
            "next_retry_at",
            "updated_at",
        ])

        return Response({"status": "RESOLVED"}, status=status.HTTP_200_OK)

    # --------------------------------------------------
    # UTIL
    # --------------------------------------------------
    @staticmethod
    def _parse_to_aware_datetime(value: str, *, start_of_day: bool) -> datetime | None:
        """
        Accepts:
        - ISO datetime: 2026-01-03T10:30:00
        - Date only:    2026-01-03
        """
        dt = parse_datetime(value)

        if dt is None:
            d = parse_date(value)
            if d:
                if start_of_day:
                    dt = datetime(d.year, d.month, d.day, 0, 0, 0)
                else:
                    dt = datetime(d.year, d.month, d.day, 23, 59, 59)

        if dt is None:
            return None

        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())

        return dt


class MonitoringConfigViewSet(viewsets.ViewSet):
    """
    GET /api/system/monitoring-config/
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        return Response(get_monitoring_config(), status=status.HTTP_200_OK)
