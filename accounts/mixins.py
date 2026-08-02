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
