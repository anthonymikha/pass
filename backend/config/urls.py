from django.contrib import admin
from django.contrib.auth.views import PasswordResetCompleteView
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from accounts.views import ResetConfirmView

# A reverse proxy will later serve the Flutter web build at / and forward
# /api/, /admin/ and /static/ here (same origin, so no CORS setup).
urlpatterns = [
    path("admin/", admin.site.urls),
    # ACC-32: the link in the reset email; Django's built-in page and token generator
    path("account/reset/<uidb64>/<token>/", ResetConfirmView.as_view(), name="password_reset_confirm"),
    path("account/reset/done/", PasswordResetCompleteView.as_view(template_name="accounts/password_reset_complete.html"),
         name="password_reset_complete"),
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
