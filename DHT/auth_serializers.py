from django.contrib.auth.models import User
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Adds custom claims into the JWT token (role, fullName, email).
    """
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Example role logic (simple):
        # - superuser => ADMIN
        # - staff => MANAGER
        # - else => OPERATOR
        if user.is_superuser:
            role = "ADMIN"
        elif user.is_staff:
            role = "MANAGER"
        else:
            role = "OPERATOR"

        full_name = (user.get_full_name() or user.username).strip()

        token["role"] = role
        token["fullName"] = full_name
        token["email"] = user.email

        return token

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ("id", "username", "email", "first_name", "last_name", "password")

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

class MeSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    fullName = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "fullName", "email", "role")

    def get_role(self, user):
        if user.is_superuser:
            return "ADMIN"
        if user.is_staff:
            return "MANAGER"
        return "OPERATOR"

    def get_fullName(self, user):
        return (user.get_full_name() or user.username).strip()
