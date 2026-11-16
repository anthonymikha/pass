from django.urls import path

from . import services, views

urlpatterns = [
    path("courts/<int:pk>/slots/", views.SlotsView.as_view()),
    path("sessions/", views.BookingView.as_view()),
    path("sessions/quote/", views.QuoteView.as_view()),
    path("sessions/<int:pk>/", views.SessionView.as_view()),
    path("sessions/<int:pk>/cancel/", views.CancelView.as_view()),
    path("sessions/<int:pk>/participants/", views.ParticipantsView.as_view()),
    path("sessions/<int:pk>/participants/<int:user_id>/", views.ParticipantView.as_view()),
    path("rentals/<int:pk>/", views.RentalView.as_view()),
    path("training-requests/", views.TrainingRequestView.as_view()),
    path("sessions/training/", views.CoachTrainingView.as_view()),
    path("sessions/<int:pk>/confirm/", views.TrainingConfirmView.as_view()),
    path("sessions/<int:pk>/decline/", views.TrainingDeclineView.as_view()),
    path("sessions/<int:pk>/withdraw/", views.TrainingWithdrawView.as_view()),
    path("users/<int:pk>/availability/", views.AvailabilityView.as_view(who=services.availability_user)),
    path("groups/<int:pk>/availability/", views.AvailabilityView.as_view(who=services.availability_group)),
    path("me/sessions/", views.MySessionsView.as_view()),
]
