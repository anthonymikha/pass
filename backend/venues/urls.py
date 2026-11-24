from django.urls import path

from . import views

urlpatterns = [
    path("sports/", views.SportList.as_view()),
    path("me/clubs/", views.MyClubsView.as_view()),
    path("clubs/", views.ClubListView.as_view()),
    path("clubs/<int:pk>/", views.ClubView.as_view()),
    path("clubs/<int:club>/currencies/", views.CurrencyList.as_view()),
    path("currencies/<int:pk>/", views.CurrencyDetail.as_view()),
    path("clubs/<int:club>/courts/", views.CourtList.as_view()),
    path("courts/<int:pk>/", views.CourtDetail.as_view()),
    path("courts/<int:court>/rates/", views.RateList.as_view()),
    path("rates/<int:pk>/", views.RateDetail.as_view()),
    path("courts/<int:court>/closures/", views.ClosureList.as_view()),
    path("closures/<int:pk>/", views.ClosureDetail.as_view()),
    path("clubs/<int:club>/equipment/", views.EquipmentList.as_view()),
    path("equipment/<int:pk>/", views.EquipmentDetail.as_view()),
    path("clubs/<int:club>/overrides/", views.OverrideList.as_view()),
    path("overrides/<int:pk>/", views.OverrideDetail.as_view()),
    path("clubs/<int:club>/offers/", views.OfferList.as_view()),
    path("offers/<int:pk>/", views.OfferDetail.as_view()),
    path("clubs/<int:club>/members/", views.MemberList.as_view()),
    path("clubs/<int:club>/coach-requests/", views.CoachRequestView.as_view()),
    path("members/<int:pk>/", views.MemberDetail.as_view()),
    path("members/<int:pk>/approve/", views.MemberApproveView.as_view()),
]
