from django.urls import path

from . import views

urlpatterns = [
    path("payments/", views.PaymentListView.as_view()),
    path("payments/<int:pk>/", views.PaymentView.as_view()),
    path("payments/<int:pk>/mark-paid/", views.PaymentPaidView.as_view(paid=True)),
    path("payments/<int:pk>/mark-due/", views.PaymentPaidView.as_view(paid=False)),
    path("clubs/<int:club>/dues/", views.DuesView.as_view()),
    path("clubs/<int:club>/revenue/", views.RevenueView.as_view()),
    path("me/earnings/", views.EarningsView.as_view()),
]
