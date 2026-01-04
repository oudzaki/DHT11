from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Ticket, Alert
from .tickets_serializers import TicketSerializer, TicketCreateFromAlertSerializer


class TicketViewSet(viewsets.ModelViewSet):
    """
    Endpoints:
    - GET    /api/tickets/
    - GET    /api/tickets/{id}/
    - PATCH  /api/tickets/{id}/        (edit title/desc/priority/status/assigned_to)
    - POST   /api/tickets/{id}/assign/ (assign to user)
    - POST   /api/tickets/{id}/close/  (close ticket)
    - POST   /api/tickets/create-from-alert/  (manual create)
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Ticket.objects.select_related("alert", "alert__sensor", "assigned_to").order_by("-created_at")
    serializer_class = TicketSerializer

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()

        status_q = request.query_params.get("status")
        priority_q = request.query_params.get("priority")
        sensor_id = request.query_params.get("sensor_id")
        alert_id = request.query_params.get("alert_id")

        if status_q:
            qs = qs.filter(status=status_q)
        if priority_q:
            qs = qs.filter(priority=priority_q)
        if sensor_id:
            qs = qs.filter(alert__sensor_id=sensor_id)
        if alert_id:
            qs = qs.filter(alert_id=alert_id)

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)

    def perform_create(self, serializer):
        # Usually tickets are created from alerts, but keep it safe:
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["POST"])
    def assign(self, request, pk=None):
        ticket = self.get_object()
        user_id = request.data.get("user_id")

        if not user_id:
            return Response({"detail": "user_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        # allow assigning to any existing user (you can restrict later)
        from django.contrib.auth.models import User
        try:
            u = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        ticket.assigned_to = u
        ticket.status = Ticket.STATUS_IN_PROGRESS if ticket.status == Ticket.STATUS_OPEN else ticket.status
        ticket.save(update_fields=["assigned_to", "status"])
        return Response({"status": "ASSIGNED", "assigned_to": u.username})

    @action(detail=True, methods=["POST"])
    def close(self, request, pk=None):
        ticket = self.get_object()
        if ticket.status == Ticket.STATUS_CLOSED:
            return Response({"detail": "Ticket already closed."}, status=status.HTTP_409_CONFLICT)

        ticket.status = Ticket.STATUS_CLOSED
        ticket.closed_at = timezone.now()
        ticket.save(update_fields=["status", "closed_at"])

        # Optionnel: si tu veux auto-resolve l’alert liée quand on close ticket
        # alert = ticket.alert
        # if alert.status != Alert.STATUS_RESOLVED:
        #     alert.status = Alert.STATUS_RESOLVED
        #     alert.resolved_by = request.user
        #     alert.resolved_at = timezone.now()
        #     alert.next_retry_at = None
        #     alert.save(update_fields=["status","resolved_by","resolved_at","next_retry_at","updated_at"])

        return Response({"status": "CLOSED"})

    @action(detail=False, methods=["POST"], url_path="create-from-alert")
    def create_from_alert(self, request):
        ser = TicketCreateFromAlertSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        alert_id = ser.validated_data["alert_id"]
        title = ser.validated_data.get("title") or ""
        description = ser.validated_data.get("description") or ""
        priority = ser.validated_data.get("priority") or Ticket.PRIORITY_MEDIUM

        alert = Alert.objects.select_related("sensor").get(id=alert_id)

        # One-to-one: only 1 ticket per alert
        if hasattr(alert, "ticket"):
            return Response(
                {"detail": "Ticket already exists for this alert.", "ticket_id": alert.ticket.id},
                status=status.HTTP_409_CONFLICT,
            )

        if not title.strip():
            title = f"Intervention required: {alert.sensor.name} (Alert #{alert.id})"

        ticket = Ticket.objects.create(
            alert=alert,
            title=title,
            description=description,
            priority=priority,
            created_by=request.user,
            status=Ticket.STATUS_OPEN,
        )

        return Response(TicketSerializer(ticket).data, status=status.HTTP_201_CREATED)
