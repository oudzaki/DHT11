from django.utils.dateparse import parse_datetime, parse_date
from django.utils import timezone
from datetime import datetime

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Alert
from .alerts_serializers import AlertSerializer, AlertDetailSerializer
from .alerts_services import get_monitoring_config


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/alerts/         -> list (filters)
    GET /api/alerts/{id}/    -> detail
    POST /api/alerts/{id}/ack/
    POST /api/alerts/{id}/resolve/
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Alert.objects.select_related("sensor").all().order_by("-created_at")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AlertDetailSerializer
        return AlertSerializer

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()

        # Filters: sensor, status, period, severity
        sensor_id = request.query_params.get("sensor_id")
        status_q = request.query_params.get("status")
        severity = request.query_params.get("severity")

        if sensor_id:
            qs = qs.filter(sensor_id=sensor_id)
        if status_q:
            qs = qs.filter(status=status_q)
        if severity:
            qs = qs.filter(severity=severity)

        # date_from/date_to
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        if date_from:
            dt = parse_datetime(date_from) or None
            if dt is None:
                d = parse_date(date_from)
                if d:
                    dt = datetime(d.year, d.month, d.day, 0, 0, 0)
            if dt:
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                qs = qs.filter(created_at__gte=dt)

        if date_to:
            dt = parse_datetime(date_to) or None
            if dt is None:
                d = parse_date(date_to)
                if d:
                    dt = datetime(d.year, d.month, d.day, 23, 59, 59)
            if dt:
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                qs = qs.filter(created_at__lte=dt)

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)

    @action(detail=True, methods=["POST"])
    def ack(self, request, pk=None):
        alert = self.get_object()
        if alert.status != Alert.STATUS_OPEN:
            return Response({"detail": "Only OPEN alerts can be acknowledged."}, status=400)

        alert.status = Alert.STATUS_ACK
        alert.acked_by = request.user
        alert.acked_at = timezone.now()
        # stop escalation => disable retries
        alert.next_retry_at = None
        alert.save(update_fields=["status", "acked_by", "acked_at", "next_retry_at", "updated_at"])

        return Response({"status": "ACKNOWLEDGED"})

    @action(detail=True, methods=["POST"])
    def resolve(self, request, pk=None):
        alert = self.get_object()
        if alert.status == Alert.STATUS_RESOLVED:
            return Response({"detail": "Alert already resolved."}, status=400)

        alert.status = Alert.STATUS_RESOLVED
        alert.resolved_by = request.user
        alert.resolved_at = timezone.now()
        alert.next_retry_at = None
        alert.save(update_fields=["status", "resolved_by", "resolved_at", "next_retry_at", "updated_at"])

        return Response({"status": "RESOLVED"})


class MonitoringConfigViewSet(viewsets.ViewSet):
    """
    GET /api/system/monitoring-config/
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        return Response(get_monitoring_config())
