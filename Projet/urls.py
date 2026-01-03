# Projet/urls.py (FULL CODE)

from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from DHT.views import (
    ReadingListCreate,
    ReadingLatest,
    SensorListCreate,
    HomeView,
    SensorPushView,
    DashboardView,
    SensorDetail,
    SensorStatusView,
    SensorLatestMeasurementView,
)

from DHT.user_views import UserViewSet
from DHT.auth_views import MyTokenObtainPairView, MeView, RegisterView, LogoutView


router = DefaultRouter()
router.register(r"users", UserViewSet, basename="users")

from DHT.alerts_views import AlertViewSet, MonitoringConfigViewSet

router.register(r"alerts", AlertViewSet, basename="alerts")

system_router = DefaultRouter()
system_router.register(r"system/monitoring-config", MonitoringConfigViewSet, basename="monitoring-config")


urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("admin/", admin.site.urls),

    # Auth JWT
    path("api/auth/login/", MyTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/me/", MeView.as_view(), name="auth_me"),
    path("api/auth/logout/", LogoutView.as_view(), name="auth_logout"),
    path("api/auth/register/", RegisterView.as_view(), name="auth_register"),

    # Users
    path("api/", include(router.urls)),

    path("api/", include(system_router.urls)),

    # Sensors (FULL CRUD + status + latest measurement)
    path("api/sensors/", SensorListCreate.as_view(), name="sensors"),
    path("api/sensors/<int:pk>/", SensorDetail.as_view(), name="sensor_detail"),
    path("api/sensors/<int:pk>/status/", SensorStatusView.as_view(), name="sensor_status"),
    path("api/sensors/<int:pk>/latest-measurement/", SensorLatestMeasurementView.as_view(), name="sensor_latest_measurement"),

    # Readings
    path("api/readings/", ReadingListCreate.as_view(), name="readings"),
    path("api/readings/latest/<str:sensor_name>/", ReadingLatest.as_view(), name="reading_latest"),

    # Push ESP -> Django
    path("api/push/", SensorPushView.as_view(), name="sensor_push"),
]
