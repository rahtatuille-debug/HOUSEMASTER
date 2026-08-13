"""
URL configuration for housemaster project.
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from students.views import SchoolViewSet, YearGroupViewSet, SchoolClassViewSet, StudentViewSet
from gradebook.views import SubjectViewSet, TermViewSet, GradeViewSet
from attendance.views import AttendanceRecordViewSet
from reporting.views import StudentReportViewSet
from accounts.views import me, InviteViewSet, InvitePreviewView, AcceptInviteView

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
router.register(r"invites", InviteViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/me/', me, name='me'),
    path('api/invites/preview/<str:token>/', InvitePreviewView.as_view(), name='invite_preview'),
    path('api/invites/accept/', AcceptInviteView.as_view(), name='invite_accept'),
    path('api/', include(router.urls)),
]