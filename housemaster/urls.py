"""
URL configuration for housemaster project.
"""
from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from students.views import SchoolViewSet, YearGroupViewSet, SchoolClassViewSet, StudentViewSet, promote_students
from gradebook.views import AssessmentTypeViewSet, SubjectViewSet, TermViewSet, GradeViewSet
from gradebook.subject_report_views import class_subject_reports
from gradebook.choices import class_subject_choices
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
from students.setup_views import (add_section, complete_setup, finish_setup, preview_report_card, register_school,
                                  setup_people, setup_state)
from students.checklist import first_week_checklist
from guardians.signup import join, signup_links, signup_requests
from accounts.teacher_home import teacher_home, tour_seen
from boarding import views as boarding_views
from boarding.views import AbsenceViewSet, DormViewSet as BoardingDormViewSet, HouseViewSet as BoardingHouseViewSet, LeaveViewSet, RollCallViewSet, SickBayViewSet
from timetable.views import LessonViewSet, PeriodViewSet, RoomViewSet, school_week as timetable_school_week, week_view as timetable_week
from support.views import SupportConcernViewSet
from support.views import suggestions as support_suggestions
from students.import_views import import_school_workbook, import_staff, import_template, staff_import_template
from reporting.analytics_views import performance
from reporting.export_views import export_attendance, export_class_list, export_grades, export_reports
from activity.views import ActivityLogViewSet
from approvals.views import ChangeRequestViewSet
from accounts.views import (
    dashboard,
    me,
    AcceptInviteView,
    ConfirmPasswordResetView,
    EmailTokenObtainPairView,
    LogoutView,
    ThrottledTokenRefreshView,
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
router.register(r"assessment-types", AssessmentTypeViewSet)
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
router.register(r"boarding/houses", BoardingHouseViewSet, basename="boarding-house")
router.register(r"boarding/dorms", BoardingDormViewSet, basename="boarding-dorm")
router.register(r"boarding/roll-calls", RollCallViewSet, basename="boarding-roll-call")
router.register(r"boarding/absences", AbsenceViewSet, basename="boarding-absence")
router.register(r"boarding/leave", LeaveViewSet, basename="boarding-leave")
router.register(r"boarding/sick-bay", SickBayViewSet, basename="boarding-sick-bay")
router.register(r"timetable/periods", PeriodViewSet, basename="timetable-period")
router.register(r"timetable/rooms", RoomViewSet, basename="timetable-room")
router.register(r"timetable/lessons", LessonViewSet, basename="timetable-lesson")
router.register(r"support/concerns", SupportConcernViewSet, basename="support-concern")

urlpatterns = [
    path(settings.ADMIN_PATH, admin.site.urls),
    path('api/token/', EmailTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', ThrottledTokenRefreshView.as_view(), name='token_refresh'),
    path('api/logout/', LogoutView.as_view(), name='logout'),
    path('api/me/', me, name='me'),
    path('api/dashboard/', dashboard, name='dashboard'),
    path('api/import/', import_school_workbook, name='import_workbook'),
    path('api/promotion/', promote_students, name='promote_students'),
    path('api/analytics/performance/', performance, name='performance'),
    path('api/import/template/', import_template, name='import_template'),
    path('api/import/staff-template/', staff_import_template, name='staff_import_template'),
    path('api/import/staff/', import_staff, name='import_staff'),
    path('api/schools/register/', register_school, name='register_school'),
    path('api/setup/', setup_state, name='setup_state'),
    path('api/subject-reports/', class_subject_reports, name='class_subject_reports'),
    path('api/subject-choices/', class_subject_choices, name='class_subject_choices'),
    path('api/setup/finish/', finish_setup, name='finish_setup'),
    path('api/setup/people/', setup_people, name='setup_people'),
    path('api/setup/complete/', complete_setup, name='complete_setup'),
    path('api/setup/add-section/', add_section, name='add_section'),
    path('api/setup/preview-report/', preview_report_card, name='preview_report_card'),
    path('api/checklist/', first_week_checklist, name='first_week_checklist'),
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
    path('api/join/<str:token>/', join, name='parent_join'),
    path('api/signup-links/', signup_links, name='signup_links'),
    path('api/teacher-home/', teacher_home, name='teacher_home'),
    path('api/boarding/overview/', boarding_views.overview, name='boarding_overview'),
    path('api/boarding/boarders/', boarding_views.boarders, name='boarding_boarders'),
    path('api/boarding/students/', boarding_views.student_search, name='boarding_students'),
    path('api/boarding/unbedded/', boarding_views.unbedded, name='boarding_unbedded'),
    path('api/boarding/beds/<int:pk>/', boarding_views.bed, name='boarding_bed'),
    path('api/timetable/week/', timetable_week, name='timetable_week'),
    path('api/timetable/school-week/', timetable_school_week, name='timetable_school_week'),
    path('api/support/suggestions/', support_suggestions, name='support_suggestions'),
    path('api/tour-seen/', tour_seen, name='tour_seen'),
    path('api/signup-requests/', signup_requests, name='signup_requests'),
    path('api/', include(router.urls)),
]
