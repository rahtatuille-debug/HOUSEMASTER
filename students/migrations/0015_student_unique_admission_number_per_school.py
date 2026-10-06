# Admission numbers (Student.external_id) become unique per school (B-5).
#
# Pre-flight: if any school already has two students with the same non-blank number, this stops before changing
# anything and says how many (counts and school IDs only). Run `python manage.py check_admission_numbers` first,
# fix them, then deploy. Existing students are never renumbered. Reverses by dropping the constraint.

from django.db import migrations, models


def preflight(apps, schema_editor):
    from students.preflight import describe, duplicate_admission_numbers

    found = duplicate_admission_numbers(apps.get_model("students", "Student"))
    if found:
        raise RuntimeError(
            "Stopped before making admission numbers unique: " + describe(found) + ". Nothing was changed. "
            "Give those students different numbers (Students page or the import sheet), then run the migration again."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0014_school_has_boarding"),
    ]

    operations = [
        migrations.RunPython(preflight, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="student",
            constraint=models.UniqueConstraint(
                condition=models.Q(("external_id", ""), _negated=True),
                fields=("school", "external_id"),
                name="unique_admission_number_per_school",
            ),
        ),
    ]
