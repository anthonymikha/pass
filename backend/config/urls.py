from django.conf import settings
from django.contrib import admin
from django.contrib.auth.views import PasswordResetCompleteView
from django.http import FileResponse, Http404
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView

from accounts.views import ResetConfirmView


def app_index(request):
    """FE-13: every app path gets the Flutter index.html (WhiteNoise has already served real files), never cached."""
    index = settings.FRONTEND_DIR / "index.html"
    if not index.is_file():
        raise Http404("The web app is not built")
    response = FileResponse(open(index, "rb"), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    return response


# The Flutter web build is served at / on the same origin as the API, so the API needs no CORS (FE-13).
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
    # Everything that is not API, admin, static files or the reset pages is an app route (deep links, refresh).
    re_path(r"^(?!(?:api|admin|static|account)(?:/|$)).*$", app_index),
]
