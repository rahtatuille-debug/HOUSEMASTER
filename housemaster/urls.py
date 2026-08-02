"""
URL configuration for housemaster project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from students.views import SchoolViewSet, SchoolClassViewSet, StudentViewSet
from gradebook.views import SubjectViewSet, TermViewSet, GradeViewSet
from attendance.views import AttendanceRecordViewSet
from reporting.views import StudentReportViewSet

router = DefaultRouter()
router.register(r"schools", SchoolViewSet)
router.register(r"school-classes", SchoolClassViewSet)
router.register(r"students", StudentViewSet)
router.register(r"subjects", SubjectViewSet)
router.register(r"terms", TermViewSet)
router.register(r"grades", GradeViewSet)
router.register(r"attendance", AttendanceRecordViewSet)
router.register(r"reports", StudentReportViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/', include(router.urls)),
]
