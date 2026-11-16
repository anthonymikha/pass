from django.urls import path

from . import views

urlpatterns = [
    path("courts/<int:pk>/slots/", views.SlotsView.as_view()),
    path("sessions/", views.BookingView.as_view()),
    path("sessions/quote/", views.QuoteView.as_view()),
    path("sessions/<int:pk>/", views.SessionView.as_view()),
    path("sessions/<int:pk>/cancel/", views.CancelView.as_view()),
    path("sessions/<int:pk>/participants/", views.ParticipantsView.as_view()),
    path("sessions/<int:pk>/participants/<int:user_id>/", views.ParticipantView.as_view()),
    path("rentals/<int:pk>/", views.RentalView.as_view()),
    path("me/sessions/", views.MySessionsView.as_view()),
]
