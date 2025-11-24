"""
URL configuration for Projet project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from DHT.views import ReadingListCreate, ReadingLatest, SensorListCreate
from DHT.views import HomeView , SensorPushView  # <= ajoute HomeView + (option push si tu l'as fait)


urlpatterns = [
	path("", HomeView.as_view(), name="home"),  # <= page d’accueil JSON
    path("admin/", admin.site.urls),
    # Auth JWT
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # DHT
    path("api/sensors/", SensorListCreate.as_view(), name="sensors"),
    path("api/readings/", ReadingListCreate.as_view(), name="readings"),
    path("api/readings/latest/<str:sensor_name>/", ReadingLatest.as_view(), name="reading_latest"),
	 # Push ESP -> Django (option A)
    path("api/push/", SensorPushView.as_view(), name="sensor_push"),
]

