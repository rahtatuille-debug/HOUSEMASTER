from rest_framework import viewsets
from .models import Subject, Term, Grade
from .serializers import SubjectSerializer, TermSerializer, GradeSerializer


class SubjectViewSet(viewsets.ModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer


class TermViewSet(viewsets.ModelViewSet):
    queryset = Term.objects.all()
    serializer_class = TermSerializer


class GradeViewSet(viewsets.ModelViewSet):
    queryset = Grade.objects.all()
    serializer_class = GradeSerializer
    filterset_fields = ["student", "subject", "term"]
