from django.urls import path

from . import views

READ_ONLY = {"http_method_names": ["get", "head", "options"]}

urlpatterns = [
    path("sessions/<int:pk>/rpe/", views.RpeView.as_view()),
    path("soreness/", views.SorenessView.as_view()),
    path("soreness/suggestions/", views.SorenessSuggestionsView.as_view()),
    path("sleep/", views.SleepView.as_view()),
    path("sleep/import/", views.SleepImportView.as_view()),
    path("sleep/<int:pk>/", views.SleepDetailView.as_view()),
    path("exercises/", views.ExerciseListView.as_view()),
    path("exercise-assignments/", views.AssignmentListView.as_view()),
    path("exercise-assignments/<int:pk>/", views.AssignmentDetailView.as_view()),
    path("exercise-assignments/<int:pk>/complete/", views.AssignmentCompleteView.as_view()),
    path("me/achievements/", views.AchievementListView.as_view()),
    # TEAM-40: a coach reads a player's logs (read only); WEL-40: sends the player an exercise
    path("players/<int:user_id>/soreness/", views.SorenessView.as_view(**READ_ONLY)),
    path("players/<int:user_id>/sleep/", views.SleepView.as_view(**READ_ONLY)),
    path("players/<int:user_id>/exercise-assignments/", views.AssignmentListView.as_view()),
    path("groups/<int:pk>/exercise-assignments/", views.TeamAssignmentsView.as_view()),
]
