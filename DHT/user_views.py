# DHT/user_views.py
from django.contrib.auth.models import User
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .permissions import IsAdmin
from .user_serializers import UserSerializer


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("id")
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsAdmin]

    def perform_destroy(self, instance: User):
        instance.is_active = False
        instance.save(update_fields=["is_active"])

        # profile peut ne pas exister => on évite crash
        profile = getattr(instance, "profile", None)
        if profile:
            profile.status = "INACTIVE"
            profile.save(update_fields=["status"])
