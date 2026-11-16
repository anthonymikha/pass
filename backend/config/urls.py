from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

# A reverse proxy will later serve the Flutter web build at / and forward
# /api/, /admin/ and /static/ here (same origin, so no CORS setup).
urlpatterns = [
    path("admin/", admin.site.urls),
    # Public on purpose: the Flutter client is generated from it.
    path("api/schema/", SpectacularAPIView.as_view(authentication_classes=[], permission_classes=[])),
    path("api/", include("accounts.urls")),
    path("api/", include("venues.urls")),
    path("api/", include("teams.urls")),
    path("api/", include("bookings.urls")),
    path("api/", include("billing.urls")),
    path("api/", include("wellness.urls")),
    path("api/", include("chat.urls")),
]
