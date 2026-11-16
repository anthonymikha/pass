from django.urls import path

from . import views

urlpatterns = [
    path("chats/", views.ChatListView.as_view()),
    path("chats/direct/", views.DirectChatView.as_view()),
    path("chats/<int:pk>/", views.ChatDetailView.as_view()),
    path("chats/<int:pk>/messages/", views.ChatMessagesView.as_view()),
    path("chats/<int:pk>/read/", views.ChatReadView.as_view()),
    path("clubs/<int:pk>/inquiries/", views.ClubInquiryView.as_view()),
]
