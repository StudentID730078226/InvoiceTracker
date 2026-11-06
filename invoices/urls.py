from django.urls import path
from . import views
app_name = "invoices"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("spending/", views.spending, name="spending"),
    path("invoices/", views.invoice_list, name="list"),
    path("invoices/review/", views.review_queue, name="review_queue"),
    path("invoices/upload/", views.upload, name="upload"),
    path('uploads/<int:pk>/review/', views.pending_review, name='pending_review'),
    path('uploads/<int:pk>/extract/', views.pending_extract, name='pending_extract'),
    path('uploads/<int:pk>/discard/', views.pending_discard, name='pending_discard'),
    path('uploads/<int:pk>/image/', views.pending_media, name='pending_media'),
    path("invoices/export/", views.export, name="export"),
    path("invoices/<int:pk>/", views.invoice_detail, name="detail"),
    path("invoices/<int:pk>/edit/", views.edit, name="edit"),
    path("invoices/<int:pk>/source/", views.source, name="source"),
    path("invoices/<int:pk>/delete/", views.delete, name="delete"),
    path("invoices/<int:pk>/action/<str:action>/", views.transition, name="transition"),
    path("invoices/<int:pk>/extract/", views.extraction_start, name="extraction_start"),
    path("invoices/<int:pk>/extractions/<int:run_id>/review/", views.extraction_review, name="extraction_review"),
]
