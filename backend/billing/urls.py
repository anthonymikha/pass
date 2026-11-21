from django.urls import path

from . import views

urlpatterns = [
    path("payments/", views.PaymentListView.as_view()),
    path("payments/<int:pk>/", views.PaymentView.as_view()),
    path("payments/<int:pk>/mark-paid/", views.PayeeTickView.as_view(action="paid")),
    path("payments/<int:pk>/mark-due/", views.PayeeTickView.as_view(action="due")),
    path("payments/<int:pk>/waive/", views.PayeeTickView.as_view(action="waive")),
    path("payments/<int:pk>/declare-paid/", views.PayerTickView.as_view(declared=True)),
    path("payments/<int:pk>/undo-declare/", views.PayerTickView.as_view(declared=False)),
    path("clubs/<int:club>/dues/", views.DuesView.as_view()),
    path("clubs/<int:club>/revenue/", views.RevenueView.as_view()),
    path("me/earnings/", views.EarningsView.as_view()),
]
