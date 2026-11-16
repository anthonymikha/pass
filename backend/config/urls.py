from django.contrib import admin
from django.urls import include, path

# A reverse proxy will later serve the Flutter web build at / and forward
# /api/, /admin/ and /static/ here (same origin, so no CORS setup).
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("accounts.urls")),
]
