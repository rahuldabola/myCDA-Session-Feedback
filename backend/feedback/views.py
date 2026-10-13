from rest_framework import generics
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsInstructorOrAdmin, IsStudentOrParent
from accounts.models import FamilyLink, User
from classes.serializers import SessionSerializer
from .models import SessionFeedback, can_submit_for, eligible_sessions_for
from .serializers import InstructorSummarySerializer, SessionFeedbackSerializer
from .summary import instructor_summary


class FeedbackCreateView(generics.CreateAPIView):
    """Submit feedback for a session (students for themselves, parents for
    a linked student). All business rules live in the serializer."""

    serializer_class = SessionFeedbackSerializer
    permission_classes = [IsStudentOrParent]


class MyFeedbackListView(generics.ListAPIView):
    """Feedback about the current student, or about a parent's linked
    students. Most recent first."""

    serializer_class = SessionFeedbackSerializer
    permission_classes = [IsStudentOrParent]

    def get_queryset(self):
        user = self.request.user
        queryset = SessionFeedback.objects.select_related(
            "session", "session__class_obj", "student", "created_by"
        ).order_by("-created_at", "-id")
        if user.role == "student":
            return queryset.filter(student=user)
        children = FamilyLink.objects.filter(
            parent=user
        ).values_list("student_id", flat=True)
        return queryset.filter(student__in=children)


class EligibleSessionsView(generics.ListAPIView):
    """Sessions the given student can still leave feedback on.

    Students get their own; parents must pass `?student=<id>` for one of
    their linked students.
    """

    serializer_class = SessionSerializer
    permission_classes = [IsStudentOrParent]

    def get_queryset(self):
        user = self.request.user
        student_id = self.request.query_params.get("student")

        if student_id is None:
            if user.role != "student":
                raise ValidationError({"student": "This parameter is required."})
            student = user
        else:
            student = User.objects.filter(
                pk=student_id if student_id.isdigit() else None,
                role=User.Role.STUDENT,
            ).first()
            # Same response for "doesn't exist" and "not yours", so the
            # endpoint can't be used to probe for student IDs.
            if student is None or not can_submit_for(user, student):
                raise PermissionDenied("You cannot submit feedback for this student.")

        return eligible_sessions_for(student).order_by("-scheduled_date")


class InstructorSummaryView(APIView):
    """Anonymized, aggregated feedback for one instructor.

    Instructors always get their own summary. Admins must pass
    `?instructor_id=<id>`.
    """

    permission_classes = [IsInstructorOrAdmin]

    def get(self, request):
        user = request.user
        instructor_id = request.query_params.get("instructor_id")

        if user.role == "instructor":
            if instructor_id is not None and instructor_id != str(user.pk):
                raise PermissionDenied("Instructors can only view their own summary.")
            instructor = user
        else:
            if not instructor_id:
                raise ValidationError({"instructor_id": "This parameter is required."})
            instructor = User.objects.filter(
                pk=instructor_id if instructor_id.isdigit() else None,
                role=User.Role.INSTRUCTOR,
            ).first()
            if instructor is None:
                raise NotFound("Instructor not found.")

        serializer = InstructorSummarySerializer(instructor_summary(instructor))
        return Response(serializer.data)
