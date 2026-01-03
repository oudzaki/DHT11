# DHT/user_serializers.py
from django.contrib.auth.models import User
from rest_framework import serializers
from .models import UserProfile


class UserSerializer(serializers.ModelSerializer):
    fullName = serializers.SerializerMethodField(read_only=True)

    # role: on l'écrit via ce champ, et on le renvoie aussi
    role = serializers.ChoiceField(
        choices=["ADMIN", "MANAGER", "OPERATOR"],
        required=False
    )

    # profile fields (read/write)
    phone = serializers.CharField(
        source="profile.phone",
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    status = serializers.ChoiceField(
        source="profile.status",
        choices=UserProfile.STATUS_CHOICES,
        required=False
    )

    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "fullName",
            "role",
            "status",
            "phone",
            "is_active",
            "password",
        )

    def get_fullName(self, user: User) -> str:
        return (user.get_full_name() or user.username).strip()

    # -------------------------
    # Role helpers
    # -------------------------
    def _apply_role(self, user: User, role: str | None):
        if role == "ADMIN":
            user.is_superuser = True
            user.is_staff = True
        elif role == "MANAGER":
            user.is_superuser = False
            user.is_staff = True
        elif role == "OPERATOR":
            user.is_superuser = False
            user.is_staff = False

    def _get_role(self, user: User) -> str:
        if user.is_superuser:
            return "ADMIN"
        if user.is_staff:
            return "MANAGER"
        return "OPERATOR"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["role"] = self._get_role(instance)
        return data

    # -------------------------
    # CREATE / UPDATE
    # -------------------------
    def create(self, validated_data):
        profile_data = validated_data.pop("profile", {})
        password = validated_data.pop("password", None)
        role = validated_data.pop("role", None)

        user = User(**validated_data)
        self._apply_role(user, role)

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save()

        # profile (assure la création)
        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                "status": profile_data.get("status", "ACTIVE"),
                "phone": profile_data.get("phone", None),
            }
        )
        return user

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", {})
        password = validated_data.pop("password", None)
        role = validated_data.pop("role", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if role is not None:
            self._apply_role(instance, role)

        if password:
            instance.set_password(password)

        instance.save()

        # profile
        profile, _ = UserProfile.objects.get_or_create(user=instance)
        if "status" in profile_data:
            profile.status = profile_data["status"]
        if "phone" in profile_data:
            profile.phone = profile_data["phone"]
        profile.save()

        return instance
