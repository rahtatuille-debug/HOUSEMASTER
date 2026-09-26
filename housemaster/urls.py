"""
URL configuration for housemaster project.
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from students.views import SchoolViewSet, YearGroupViewSet, SchoolClassViewSet, StudentViewSet, promote_students
from gradebook.views import SubjectViewSet, TermViewSet, GradeViewSet
from attendance.views import AttendanceRecordViewSet
from reporting.views import StudentReportViewSet
from communications.views import AnnouncementViewSet, UrgentAlertViewSet
from guardians.views import (
    AcceptGuardianInviteView,
    GuardianInvitePreviewView,
    GuardianInviteViewSet,
    GuardianStudentViewSet,
    ParentViewSet,
    guardian_me,
)
from messaging.views import ConversationViewSet
from students.import_views import import_school_workbook, import_template
from reporting.export_views import export_attendance, export_class_list, export_grades, export_reports
from activity.views import ActivityLogViewSet
from approvals.views import ChangeRequestViewSet
from accounts.views import (
    dashboard,
    me,
    AcceptInviteView,
    ConfirmPasswordResetView,
    EmailTokenObtainPairView,
    InvitePreviewView,
    InviteViewSet,
    RequestPasswordResetView,
    StaffViewSet,
    TeachingAssignmentViewSet,
)

router = DefaultRouter()
router.register(r"schools", SchoolViewSet)
router.register(r"year-groups", YearGroupViewSet)
router.register(r"school-classes", SchoolClassViewSet)
router.register(r"students", StudentViewSet)
router.register(r"subjects", SubjectViewSet)
router.register(r"terms", TermViewSet)
router.register(r"grades", GradeViewSet)
router.register(r"attendance", AttendanceRecordViewSet)
router.register(r"reports", StudentReportViewSet)
router.register(r"announcements", AnnouncementViewSet)
router.register(r"alerts", UrgentAlertViewSet, basename="alert")
router.register(r"invites", InviteViewSet)
router.register(r"staff", StaffViewSet)
router.register(r"teaching-assignments", TeachingAssignmentViewSet)
router.register(r"guardian-invites", GuardianInviteViewSet)
router.register(r"parents", ParentViewSet)
router.register(r"guardian-students", GuardianStudentViewSet, basename="guardian-student")
router.register(r"conversations", ConversationViewSet, basename="conversation")
router.register(r"activity", ActivityLogViewSet)
router.register(r"change-requests", ChangeRequestViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/token/', EmailTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/me/', me, name='me'),
    path('api/dashboard/', dashboard, name='dashboard'),
    path('api/import/', import_school_workbook, name='import_workbook'),
    path('api/promotion/', promote_students, name='promote_students'),
    path('api/import/template/', import_template, name='import_template'),
    path('api/exports/class-list/', export_class_list, name='export_class_list'),
    path('api/exports/grades/', export_grades, name='export_grades'),
    path('api/exports/attendance/', export_attendance, name='export_attendance'),
    path('api/exports/reports/', export_reports, name='export_reports'),
    path('api/invites/preview/<str:token>/', InvitePreviewView.as_view(), name='invite_preview'),
    path('api/invites/accept/', AcceptInviteView.as_view(), name='invite_accept'),
    path('api/password-reset/', RequestPasswordResetView.as_view(), name='password_reset_request'),
    path('api/password-reset/confirm/', ConfirmPasswordResetView.as_view(), name='password_reset_confirm'),
    path('api/guardian-invites/preview/<str:token>/', GuardianInvitePreviewView.as_view(), name='guardian_invite_preview'),
    path('api/guardian-invites/accept/', AcceptGuardianInviteView.as_view(), name='guardian_invite_accept'),
    path('api/guardian-me/', guardian_me, name='guardian_me'),
    path('api/', include(router.urls)),
]
