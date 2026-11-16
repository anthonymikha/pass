from django.urls import path

from . import views

urlpatterns = [
    path("groups/", views.GroupCreateView.as_view()),
    path("groups/<int:pk>/", views.GroupDetailView.as_view()),
    path("groups/<int:pk>/members/", views.GroupMembersView.as_view()),
    path("groups/<int:pk>/members/<int:user_id>/", views.GroupMemberDetailView.as_view()),
    path("groups/<int:pk>/members/<int:user_id>/accept/", views.GroupMemberAcceptView.as_view()),
    path("groups/<int:pk>/accept/", views.GroupAcceptView.as_view()),
    path("groups/<int:pk>/join/", views.GroupJoinView.as_view()),
    path("groups/<int:pk>/shadow-players/", views.GroupShadowPlayersView.as_view()),
    path("groups/<int:pk>/coach/", views.GroupCoachView.as_view()),
    path("users/", views.UserSearchView.as_view()),
    path("users/<int:pk>/", views.PublicProfileView.as_view()),
    path("coaches/", views.CoachSearchView.as_view()),
]
