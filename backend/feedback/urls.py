from django.urls import path
from . import views

urlpatterns = [
    path("", views.FeedbackCreateView.as_view(), name="feedback-create"),
    path("my/", views.MyFeedbackListView.as_view(), name="my-feedback"),
    path(
        "eligible-sessions/",
        views.EligibleSessionsView.as_view(),
        name="eligible-sessions",
    ),
    path(
        "instructor-summary/",
        views.InstructorSummaryView.as_view(),
        name="instructor-summary",
    ),
]
