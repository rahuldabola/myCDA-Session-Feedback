from django.contrib import admin
from .models import SessionFeedback


@admin.register(SessionFeedback)
class SessionFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "student",
        "created_by",
        "rating_clarity",
        "rating_engagement",
        "rating_pace",
        "created_at",
    )
    list_filter = ("session__class_obj",)
