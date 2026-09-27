from django.db import models

from gradebook.levels import SCALE_LABELS


class School(models.Model):
    """A tenant school using HouseMaster."""
    name = models.CharField(max_length=255)
    report_tone = models.CharField(
        max_length=50,
        choices=[
            ("formal", "Formal"),
            ("warm", "Warm / encouraging"),
            ("concise", "Concise / direct"),
        ],
        default="formal",
        help_text="School-level tone setting for AI-generated report comments (v1: per-school, not per-teacher).",
    )
    grading_scale = models.CharField(
        max_length=10, choices=list(SCALE_LABELS.items()), default="cbc4",
        help_text="Which performance levels to show next to percentages. See gradebook.levels.",
    )
    privacy_contact = models.CharField(
        max_length=255, blank=True,
        help_text="Who people contact about their personal data (Kenya Data Protection Act), e.g. an email address.",
    )
    education_system = models.CharField(
        max_length=20, blank=True,
        choices=[("cbc", "CBC"), ("844", "8-4-4"), ("british", "British / Cambridge"),
                 ("ib", "International Baccalaureate"), ("american", "American")],
        help_text="Chosen in the setup wizard. See students.presets.",
    )
    country = models.CharField(
        max_length=10, default="ke",
        choices=[("ke", "Kenya"), ("gb", "United Kingdom"), ("us", "United States"), ("other", "Another country")],
        help_text="Decides the privacy law named in the privacy notice and local formats. See students.presets.",
    )
    # Shown on report cards and to parents.
    motto = models.CharField(max_length=255, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    # The setup wizard: a school can't use the app until its first admin
    # finishes it. Their choices so far are kept so they can come back later.
    setup_progress = models.JSONField(default=dict, blank=True)
    # The school's own words where they differ from its system's, e.g.
    # {"term": "Quarter", "terms": "Quarters"}. See students.presets.school_vocab.
    vocab_overrides = models.JSONField(default=dict, blank=True)
    # Setup has two parts: the structure (system, classes, subjects, terms), then
    # people (staff, students, parents). The school opens once both are done.
    structure_completed_at = models.DateTimeField(null=True, blank=True)
    setup_completed_at = models.DateTimeField(null=True, blank=True)
    # The admin hid the first-week checklist on the home page.
    checklist_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class YearGroup(models.Model):
    """A year/grade level within a school, e.g. 'Year 7', 'Grade 9'."""
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="year_groups")
    name = models.CharField(max_length=100)
    # Year groups in the order students move through them, and whether this is
    # the school's last year (its students graduate at the end of the year).
    order = models.PositiveSmallIntegerField(default=0)
    is_final = models.BooleanField(default=False)
    # A school running two systems (e.g. CBC with a British IGCSE section)
    # sets these on the other section's year groups; blank means the school's.
    education_system = models.CharField(max_length=20, blank=True)
    grading_scale = models.CharField(max_length=10, blank=True)

    class Meta:
        unique_together = ("school", "name")

    def __str__(self):
        return f"{self.school.name} - {self.name}"


class SchoolClass(models.Model):
    """A specific class/section within a year group, e.g. '7A'."""
    year_group = models.ForeignKey(YearGroup, on_delete=models.CASCADE, related_name="classes")
    name = models.CharField(max_length=100)
    house = models.CharField(max_length=100, blank=True)

    class Meta:
        unique_together = ("year_group", "name")

    def __str__(self):
        return f"{self.year_group.name} - {self.name}"


class Student(models.Model):
    """Core student record — the spine other modules (gradebook, attendance, reporting) hang off."""
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="students")
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name="students"
    )
    external_id = models.CharField(
        max_length=100, blank=True,
        help_text="Student ID as used in the school's own Excel sheet (Students.id column), for import matching.",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    house = models.CharField(max_length=100, blank=True)
    enrolled_on = models.DateField(null=True, blank=True, verbose_name="admission date")
    is_active = models.BooleanField(default=True)
    graduated_on = models.DateField(null=True, blank=True, help_text="Set when they leave from a final year.")
    pathway = models.CharField(
        max_length=60, blank=True, help_text="CBC senior school pathway, e.g. STEM. See students.presets.PATHWAYS.",
    )

    class Gender(models.TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        OTHER = "other", "Other"

    class ModeOfLearning(models.TextChoices):
        DAY = "day", "Day"
        BOARDING = "boarding", "Boarding"

    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=60, blank=True)
    mode_of_learning = models.CharField(max_length=10, choices=ModeOfLearning.choices, blank=True)
    medical_notes = models.TextField(
        blank=True, verbose_name="health notes",
        help_text="Allergies, conditions or medication staff should know about.",
    )
    # Stored in the database rather than as a file: Render's free tier wipes
    # uploaded files on every deploy. Resized to a small JPEG on upload
    # (students.photos), so it stays small.
    photo = models.BinaryField(null=True, blank=True, editable=False)
    photo_updated_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        indexes = [models.Index(fields=["school", "external_id"])]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
