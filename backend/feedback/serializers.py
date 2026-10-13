from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from core.middleware import get_current_user
from core.serializers import BaseModelSerializer
from accounts.models import User
from accounts.serializers import UserMinimalSerializer
from classes.models import ClassEnrollment, Session
from .models import (
    FEEDBACK_WINDOW_DAYS,
    SessionFeedback,
    can_submit_for,
    feedback_window_start,
)

DUPLICATE_FEEDBACK_MESSAGE = (
    "Feedback has already been submitted for this student for this session."
)


class SessionFeedbackSerializer(BaseModelSerializer):
    """
    Student/parent-facing feedback, used for submission and history.

    Includes the student, submitter and note, so it must never be used on
    an instructor-facing endpoint -- see InstructorSummarySerializer.

    `created_by` (the submitter) is not a writable field: any value in the
    request body is ignored and BaseModelSerializer.create() fills it from
    the request user.
    """

    student = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.STUDENT),
        required=False,
        help_text="Required for parents. Students default to themselves.",
    )
    student_display = UserMinimalSerializer(source="student", read_only=True)
    class_name = serializers.CharField(
        source="session.class_obj.name", read_only=True
    )
    session_date = serializers.DateTimeField(
        source="session.scheduled_date", read_only=True
    )
    session_topic = serializers.CharField(source="session.topic", read_only=True)

    class Meta:
        model = SessionFeedback
        fields = [
            "id",
            "session",
            "session_date",
            "class_name",
            "session_topic",
            "student",
            "student_display",
            "rating_clarity",
            "rating_engagement",
            "rating_pace",
            "note",
            "created_by_display",
            "created_at",
            "updated_at",
        ]
        # DRF would auto-add a UniqueTogetherValidator for (session, student),
        # which forces `student` to be required and runs before we can
        # default it to the submitting student. The duplicate check lives in
        # validate() instead, with a friendlier message.
        validators = []

    def validate(self, attrs):
        user = get_current_user()
        if user is None or not user.is_authenticated:
            raise PermissionDenied("Authentication required.")

        session = attrs["session"]
        student = attrs.get("student")

        if student is None:
            if user.role != User.Role.STUDENT:
                raise serializers.ValidationError(
                    {"student": "Select which student this feedback is for."}
                )
            student = attrs["student"] = user

        if not can_submit_for(user, student):
            raise PermissionDenied(
                "You can only submit feedback for yourself or a student "
                "linked to your account."
            )

        if session.status != Session.Status.COMPLETED:
            raise serializers.ValidationError(
                {"session": "Feedback can only be submitted for completed sessions."}
            )

        if session.scheduled_date < feedback_window_start():
            raise serializers.ValidationError(
                {
                    "session": (
                        "Feedback is only accepted within "
                        f"{FEEDBACK_WINDOW_DAYS} days of a session."
                    )
                }
            )

        if not ClassEnrollment.objects.filter(
            class_obj_id=session.class_obj_id, student=student, is_active=True
        ).exists():
            raise serializers.ValidationError(
                {"session": "This student is not enrolled in this session's class."}
            )

        if SessionFeedback.objects.filter(session=session, student=student).exists():
            raise serializers.ValidationError(DUPLICATE_FEEDBACK_MESSAGE)

        return attrs

    def create(self, validated_data):
        # Two concurrent submissions can both pass validate(); the database
        # unique constraint rejects the second, which we report the same way.
        try:
            with transaction.atomic():
                return super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError(DUPLICATE_FEEDBACK_MESSAGE)


class DimensionAveragesSerializer(serializers.Serializer):
    clarity = serializers.FloatField()
    engagement = serializers.FloatField()
    pace = serializers.FloatField()
    overall = serializers.FloatField()


class InstructorSummarySerializer(serializers.Serializer):
    """
    Instructor-facing, aggregate-only response.

    This is deliberately a plain Serializer with an explicit allow-list of
    numeric fields, not a model serializer over SessionFeedback: there is
    no path from here to a student, submitter, note, or per-session row.
    (BaseModelSerializer doesn't fit either -- there is no model instance,
    and it would add `created_by_display`, an identity field.)
    """

    instructor_id = serializers.IntegerField()
    window_size = serializers.IntegerField()
    sessions_in_window = serializers.IntegerField()
    sessions_with_feedback = serializers.IntegerField()
    total_feedback = serializers.IntegerField()
    min_feedback_for_scores = serializers.IntegerField()
    averages = DimensionAveragesSerializer(allow_null=True)
