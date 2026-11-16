from django.urls import path

from . import services, views

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view()),
    path("auth/login/", views.LoginView.as_view()),
    path("auth/logout/", views.LogoutView.as_view()),
    path("devices/", views.DeviceView.as_view()),
    path("devices/<str:key>/", views.DeviceDetailView.as_view()),
    path("me/", views.MeView.as_view()),
    path("me/avatar/", views.AvatarView.as_view()),
    path("me/avatar/form/", views.AvatarFormView.as_view()),
    path("me/blockouts/", views.BlockoutListView.as_view()),
    path("me/blockouts/<int:pk>/", views.BlockoutDetailView.as_view()),
    path("friends/", views.FriendsView.as_view(people=services.friends_of)),
    path("friends/incoming/", views.PeopleListView.as_view(people=services.incoming_friend_requests)),
    path("friends/outgoing/", views.PeopleListView.as_view(people=services.outgoing_friend_requests)),
    path("friends/<int:user_id>/", views.FriendDetailView.as_view()),
    path("friends/<int:user_id>/accept/", views.FriendAcceptView.as_view()),
    path("blocks/", views.BlocksView.as_view(people=services.blocked_users)),
    path("blocks/<int:user_id>/", views.BlockDetailView.as_view()),
    path("coaching/", views.CoachingView.as_view()),
    path("coaching/<int:pk>/", views.CoachingDetailView.as_view()),
    path("coaching/<int:pk>/accept/", views.CoachingAcceptView.as_view()),
    path("shadow-players/", views.ShadowPlayerListView.as_view()),
    path("shadow-players/<int:pk>/", views.ShadowPlayerDetailView.as_view()),
]
