from rest_framework.exceptions import PermissionDenied

from .permissions import HasSchoolProfile


class SchoolScopedViewSetMixin:
    """
    Restricts a ModelViewSet's queryset to rows belonging to the requesting
    user's school, so one school's data is never visible in another
    school's API responses.

    Set `school_lookup` to the ORM path from this model to School:
      - "id" if the model IS School itself
      - "school" if the model has a direct FK to School
      - "student__school" if it only reaches School via a Student FK
      - "year_group__school" for SchoolClass, etc.

    Also adds HasSchoolProfile to permission_classes automatically.
    """

    school_lookup = "school"
    permission_classes = [HasSchoolProfile]

    def get_school(self):
        return self.request.user.profile.school

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(**{self.school_lookup: self.get_school()})

    def check_belongs_to_school(self, obj, field_name="This"):
        """
        Call from perform_create/perform_update for any related object
        (student, subject, term, year_group, ...) pulled from validated_data,
        to stop a caller from linking a record to another school's data via
        a spoofed foreign key ID in the request body.

        `obj` may be the School itself, or anything with a `.school`
        attribute reachable in one hop.
        """
        obj_school = obj if obj.__class__.__name__ == "School" else obj.school
        if obj_school != self.get_school():
            raise PermissionDenied(f"{field_name} does not belong to your school.")


def requester_school(request):
    """The school of the logged-in staff member or parent, or None."""
    user = getattr(request, "user", None)
    owner = getattr(user, "profile", None) or getattr(user, "guardian", None)
    return owner.school if owner is not None else None


# How to reach School from each model a serializer can link to.
_SCHOOL_PATHS = {
    "School": "pk",
    "Student": "school",
    "Subject": "school",
    "Term": "school",
    "YearGroup": "school",
    "SchoolClass": "year_group__school",
    "Profile": "school",
}


class SchoolScopedRelatedFieldsMixin:
    """
    For serializers: every writable link to another record (student,
    subject, term, class, teacher, ...) only accepts records from the
    requester's own school.

    Another school's record is then rejected exactly like an ID that
    doesn't exist ("Invalid pk ... object does not exist"), so the error
    can't be used to learn what exists at another school. The views'
    check_belongs_to_school() calls stay as a second line of defence.
    """

    def get_fields(self):
        fields = super().get_fields()
        school = requester_school(self.context.get("request"))
        for field in fields.values():
            relation = getattr(field, "child_relation", field)
            queryset = getattr(relation, "queryset", None)
            if queryset is None:
                continue
            model_name = queryset.model.__name__
            if school is None:
                relation.queryset = queryset.none()
            elif model_name in _SCHOOL_PATHS:
                relation.queryset = queryset.filter(**{_SCHOOL_PATHS[model_name]: school})
            elif model_name == "User":
                from django.db.models import Q

                relation.queryset = queryset.filter(Q(profile__school=school) | Q(guardian__school=school))
            else:
                raise AssertionError(f"No school scoping rule for linked model {model_name}")
        return fields
