"""
"HouseMaster Demo College": a large British secondary school (Years 7 to 13,
about 1,000 students) that has used HouseMaster for five school years.

Unlike the small demo schools it has history: every finished term of the
last five school years has its marks and finalized report cards, students
move up each September, Year 11s leave or stay on for the sixth form, Year
13s graduate, and new Year 7s arrive. Former students are kept as inactive,
with their marks and reports. This school year's attendance is recorded so
far; earlier years have no registers (to keep the database small).

It is too big to build on every deploy, so it has its own command
(seed_large_demo) and is never created by seed_demo_school. Its logins are
on college.housemaster-demo.example and share DEMO_PASSWORD.
"""
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.utils import timezone

from accounts.models import Profile, TeachingAssignment
from activity.services import log_activity
from attendance.models import AttendanceRecord
from communications.models import Announcement
from gradebook.levels import level_for
from gradebook.models import AssessmentType, Grade, StudentSubject, Subject, SubjectReport, Term
from guardians.models import Guardian
from reporting.models import StudentReport

from .models import School, SchoolClass, Student, YearGroup
from .presets import suggested_terms
from .samples import PRINCIPAL_COMMENT, SUBJECT_COMMENTS, TEACHER_COMMENTS, band

NAME = "HouseMaster Demo College"
DOMAIN = "college.housemaster-demo.example"
YEARS_ACTIVE = 5
HOUSES = ["Austen", "Brunel", "Darwin", "Newton"]

GIRLS = ["Olivia", "Amelia", "Isla", "Ava", "Grace", "Freya", "Sophie", "Priya", "Ella", "Maya", "Zara", "Chloe",
         "Ruby", "Aisha", "Poppy", "Emily", "Lily", "Hannah", "Evie", "Mia", "Layla", "Sienna", "Anika", "Imogen",
         "Florence", "Matilda", "Esme", "Nadia", "Leah", "Rosie", "Harriet", "Alice", "Naomi", "Yasmin", "Phoebe",
         "Charlotte", "Lucy", "Eleanor", "Sara", "Wanjiru"]
BOYS = ["Oliver", "George", "Harry", "Noah", "Jack", "Leo", "Arthur", "Oscar", "Samuel", "Rohan", "Theo", "Max",
        "Ethan", "Yusuf", "Finn", "James", "William", "Henry", "Alfie", "Charlie", "Joshua", "Adam", "Isaac",
        "Reuben", "Hugo", "Kian", "Aarav", "Zain", "Daniel", "Thomas", "Edward", "Lewis", "Nathan", "Ibrahim",
        "Felix", "Toby", "Elliot", "Kofi", "Marcus", "Otieno"]
SURNAMES = ["Smith", "Jones", "Taylor", "Brown", "Williams", "Wilson", "Johnson", "Davies", "Patel", "Wright",
            "Evans", "Thomas", "Roberts", "Khan", "Walker", "Hughes", "Green", "Clarke", "Bennett", "Hall", "Wood",
            "Turner", "Martin", "Cooper", "Hill", "Ward", "Morris", "Moore", "King", "Harris", "Baker", "Lewis",
            "Allen", "Young", "Mitchell", "Shah", "Ahmed", "Ali", "Begum", "Kaur", "Singh", "Okafor", "Mensah",
            "Kamau", "Otieno", "Mwangi", "Nguyen", "Chen", "Rossi", "Murphy", "O'Brien", "Campbell", "Scott",
            "Reid", "Stewart", "Fraser", "Lloyd", "Price", "Morgan", "Kelly"]

# Key Stage 3 (Years 7-9): everyone takes these.
KS3 = ["English Language", "Mathematics", "Biology", "Chemistry", "Physics", "History", "Geography", "French",
       "Computer Science", "Art and Design"]
# GCSE (Years 10-11): the core, plus three options chosen at the start of Year 10.
GCSE_CORE = ["English Language", "English Literature", "Mathematics", "Biology", "Chemistry", "Physics"]
GCSE_OPTIONS = ["History", "Geography", "French", "Spanish", "Computer Science", "Art and Design", "Music", "Drama",
                "Religious Studies", "Business"]
# A level (Years 12-13): three subjects chosen at the start of Year 12.
A_LEVELS = ["Mathematics", "Further Mathematics", "Biology", "Chemistry", "Physics", "English Literature", "History",
            "Geography", "Economics", "Psychology", "Computer Science", "Art and Design", "French", "Business"]
SUBJECTS = list(dict.fromkeys(KS3 + GCSE_CORE + GCSE_OPTIONS + A_LEVELS))
ASSESSMENTS = [("Classwork", 40), ("Assessment week", 60)]

# Students per year group, in forms: Years 7-11 have five forms, the sixth form six smaller ones.
MAIN_FORMS, MAIN_SIZE = "ABCDE", 28
SIXTH_FORMS, SIXTH_SIZE = "ABCDEF", 25
STAY_ON = 0.7  # of Year 11s who continue into Year 12
MAX_LESSONS = 24  # a teacher's lessons a week

LEADERS = [("Catherine Hale", "principal", "Principal"), ("Marcus Reid", "deputy", "Deputy head"),
           ("Anika Patel", "sixthform", "Head of sixth form")]


def demo_users():
    return User.objects.filter(email__iendswith=f"@{DOMAIN}")


def _school_year(today):
    """The calendar year the current school year started in (September)."""
    return today.year if today.month >= 7 else today.year - 1


class _Pupil:
    __slots__ = ("record", "group", "form", "ability", "trend", "aptitude", "options", "a_levels", "absent_rate",
                 "joined")

    def __init__(self, group, joined, rng):
        self.record = None
        self.group = group  # 7 to 13
        self.form = None
        self.joined = joined
        self.ability = max(25, min(95, rng.gauss(62, 12)))
        self.trend = rng.gauss(0, 2.5)  # points a year, so some improve and some slip
        self.aptitude = {name: rng.gauss(0, 6) for name in SUBJECTS}
        self.options = []
        self.a_levels = []
        self.absent_rate = 0.15 if rng.random() < 0.04 else 0.03

    def subjects(self):
        if self.group <= 9:
            return KS3
        if self.group <= 11:
            return GCSE_CORE + self.options
        return self.a_levels


def build(password_hash, today=None, scale=1.0):
    """Create the school. `scale` shrinks it for tests (1.0 is about 1,000 students). Returns a summary."""
    rng = random.Random("college-2026")
    today = today or timezone.localdate()
    now = timezone.now()
    main_size = max(2, round(MAIN_SIZE * scale))
    sixth_size = max(2, round(SIXTH_SIZE * scale))
    main_forms = MAIN_FORMS if scale >= 0.5 else MAIN_FORMS[:2]
    sixth_forms = SIXTH_FORMS if scale >= 0.5 else SIXTH_FORMS[:2]
    target = {g: (len(sixth_forms) * sixth_size if g >= 12 else len(main_forms) * main_size) for g in range(7, 14)}

    school = School.objects.create(
        name=NAME, education_system="british", grading_scale="igcse9", country="gb", report_tone="warm",
        motto="Learning for life", address="Riverside Drive, Nairobi", phone="+44 0000 000 200",
        email=f"office@{DOMAIN}", setup_completed_at=now - timedelta(days=365 * YEARS_ACTIVE),
    )

    # --- structure
    year_groups, forms = {}, {}
    for g in range(7, 14):
        year_groups[g] = YearGroup.objects.create(school=school, name=f"Year {g}", order=g - 7, is_final=g == 13,
                                                  grading_scale="igcse" if g >= 12 else "")
        for letter in (sixth_forms if g >= 12 else main_forms):
            forms[(g, letter)] = SchoolClass.objects.create(year_group=year_groups[g], name=f"{g}{letter}",
                                                            house=HOUSES[len(forms) % len(HOUSES)])
    subjects = {n: Subject.objects.create(school=school, name=n, is_elective=True) for n in SUBJECTS}
    types = [AssessmentType.objects.create(school=school, name=n, weight=w, order=i)
             for i, (n, w) in enumerate(ASSESSMENTS)]
    weight = {t.id: float(t.weight) for t in types}

    first_year = _school_year(today) - YEARS_ACTIVE
    years = []  # [(start year, [Term, ...])]
    for y in range(first_year, _school_year(today) + 1):
        made = []
        for spec in suggested_terms("british", date(y, 9, 1)):
            start, end = date.fromisoformat(spec["start_date"]), date.fromisoformat(spec["end_date"])
            locked = end < date(_school_year(today), 9, 1) - timedelta(days=365)
            made.append(Term.objects.create(school=school, name=spec["name"], start_date=start, end_date=end,
                                            is_locked=locked,
                                            locked_at=now - timedelta(days=(today - end).days - 21) if locked else None))
        years.append((y, made))
    current = max((t for _, ts in years for t in ts if t.start_date <= today), key=lambda t: t.start_date)

    # --- staff: leaders (admins), then teachers by subject, with form tutors
    def user(local, name):
        first, _, last = name.partition(" ")
        return User.objects.create(username=f"{local}@{DOMAIN}", email=f"{local}@{DOMAIN}", password=password_hash,
                                   first_name=first, last_name=last,
                                   last_login=now - timedelta(days=rng.randint(0, 6), hours=rng.randint(1, 10)))

    leaders = [Profile.objects.create(user=user(local, name), school=school, role="admin", display_name=name)
               for name, local, _ in LEADERS]
    # Teachers are taken on as the timetable needs them (see the assignments below).
    teachers_for, load = {}, {}
    taken_names = {name for name, _, _ in LEADERS}

    def new_teacher(subject):
        while True:
            name = f"{rng.choice(GIRLS + BOYS)} {rng.choice(SURNAMES)}"
            if name not in taken_names:
                break
        taken_names.add(name)
        # The first Mathematics teacher has the well-known teacher@ login.
        local = "teacher" if subject == "Mathematics" and "Mathematics" not in teachers_for else \
            f"{name.split()[0][0].lower()}.{name.split()[1].lower().replace(chr(39), '')}{len(load)}"
        profile = Profile.objects.create(user=user(local, name), school=school, role="teacher", display_name=name)
        teachers_for.setdefault(subject, []).append(profile)
        load[profile.id] = 0
        return profile

    def teacher_for(subject, lessons):
        """The least busy teacher of the subject with room for these lessons (24 a week), or a new one."""
        fits = [t for t in teachers_for.get(subject, []) if load[t.id] + lessons <= MAX_LESSONS]
        teacher = min(fits, key=lambda t: load[t.id]) if fits else new_teacher(subject)
        load[teacher.id] += lessons
        return teacher

    # --- people: the school as it was five years ago, then each September
    def new_pupil(group, joined):
        p = _Pupil(group, joined, rng)
        if group >= 10:
            choose_options(p)
        if group >= 12:
            choose_a_levels(p)
        everyone.append(p)
        return p

    def choose_options(p):
        p.options = rng.sample(GCSE_OPTIONS, 3)

    def choose_a_levels(p):
        ranked = sorted(A_LEVELS, key=lambda s: -(p.aptitude[s] + rng.gauss(0, 4)))
        picks = [s for s in ranked if s != "Further Mathematics"][:3]
        if "Mathematics" in picks and p.ability > 70 and rng.random() < 0.4:
            picks[-1] = "Further Mathematics"
        p.a_levels = picks

    everyone = []
    roll = {g: [new_pupil(g, first_year) for _ in range(target[g])] for g in range(7, 14)}
    leavers = []  # (pupil, left on, graduated)
    history = []  # per school year: {group: [pupils]}

    for index, (y, _) in enumerate(years):
        if index:
            # September: Year 13 graduates, Year 11s mostly stay on, a few leave from every year, Year 7 arrives.
            for p in roll[13]:
                leavers.append((p, date(y, 7, 10), True))
            for g in range(12, 6, -1):
                moving = []
                for p in roll[g]:
                    stays = rng.random() < (STAY_ON + (p.ability - 62) / 100 if g == 11 else 0.97)
                    if stays:
                        moving.append(p)
                    else:
                        leavers.append((p, date(y, 7, 10), False))
                for p in moving:
                    p.group = g + 1
                    if p.group == 10:
                        choose_options(p)
                    if p.group == 12:
                        choose_a_levels(p)
                roll[g + 1] = moving
            roll[7] = []
            for g in range(7, 14):
                while len(roll[g]) < target[g]:
                    roll[g].append(new_pupil(g, y))
        for g in range(7, 14):
            letters = sixth_forms if g >= 12 else main_forms
            for i, p in enumerate(roll[g]):
                # Main school forms stay together; the sixth form is re-formed each year.
                if p.form is None or g in (7, 12) or p.form not in letters:
                    p.form = letters[i % len(letters)]
        history.append({g: [(p, p.form) for p in roll[g]] for g in range(7, 14)})

    # --- student records
    current_roll = {id(p) for g in roll.values() for p in g}
    left = {id(p): (on, graduated) for p, on, graduated in leavers}
    records = []
    for n, p in enumerate(everyone, start=1):
        female = rng.random() < 0.5
        active = id(p) in current_roll
        age_in_year7 = 11
        joined_group = _joined_group(p, history, years)
        dob_year = p.joined - age_in_year7 - (joined_group - 7)
        on, graduated = left.get(id(p), (None, False))
        records.append(Student(
            school=school, external_id=f"HDC/{p.joined}/{n:04d}",
            first_name=rng.choice(GIRLS if female else BOYS), last_name=rng.choice(SURNAMES),
            gender="female" if female else "male", nationality=rng.choice(["British", "Kenyan", "Kenyan", "Indian",
                                                                           "Nigerian", "American", "Ugandan"]),
            date_of_birth=date(dob_year, 9, 1) + timedelta(days=rng.randint(0, 364)),
            enrolled_on=date(p.joined, 9, 4), mode_of_learning="day" if rng.random() < 0.85 else "boarding",
            house=HOUSES[n % len(HOUSES)], is_active=active,
            school_class=forms[(p.group, p.form)] if active else None,
            graduated_on=on if graduated else None,
            medical_notes="Asthma: inhaler kept in the school office." if rng.random() < 0.03 else "",
        ))
    Student.objects.bulk_create(records, batch_size=1000)
    saved = list(Student.objects.filter(school=school).order_by("id"))
    for p, s in zip(everyone, saved):
        p.record = s

    # Current subject choices, and who teaches each subject in each form.
    StudentSubject.objects.bulk_create([
        StudentSubject(student=p.record, subject=subjects[name])
        for g in roll.values() for p in g for name in p.subjects()
    ], batch_size=2000)
    from timetable.services import lessons_per_week

    assignments, tutored = [], []
    for (g, letter), klass in sorted(forms.items(), key=lambda kv: (kv[0][0] != 9, kv[0])):
        taught = sorted({name for p in roll[g] if p.form == letter for name in p.subjects()})
        for name in taught:
            assignments.append(TeachingAssignment(teacher=teacher_for(name, lessons_per_week(name, f"Year {g}")),
                                                  school_class=klass, subject=subjects[name]))
        tutored.append(klass)
    teachers = [p for ps in teachers_for.values() for p in ps]
    for i, klass in enumerate(tutored):
        assignments.append(TeachingAssignment(teacher=teachers[i % len(teachers)], school_class=klass, subject=None))
    TeachingAssignment.objects.bulk_create(assignments)
    # The teacher@ login tutors 9A (and, being the first Maths teacher, teaches it Mathematics).
    star = teachers_for["Mathematics"][0]
    TeachingAssignment.objects.filter(school_class=forms[(9, main_forms[0])], subject=None).update(teacher=star)

    # --- marks and report cards, one term at a time (keeps memory low)
    grade_count = report_count = 0
    principal = leaders[0]
    for index, (y, terms) in enumerate(years):
        roster = [p for ps in history[index].values() for p, _ in ps]
        then = {id(p): (g, form) for g, ps in history[index].items() for p, form in ps}
        for number, term in enumerate(terms):
            if term.start_date > today:
                continue
            finished = term != current
            elapsed = index + number / 3
            grades, entries, reports = [], [], []
            for p in roster:
                g, form = then[id(p)]
                klass = forms[(g, form)]
                taken = _subjects_then(p, g)
                if not finished:
                    taken = taken[:5]
                scores = {}
                for name in taken:
                    base = p.ability + p.aptitude[name] + p.trend * elapsed
                    total = weights = 0.0
                    for kind in (types if finished else types[:1]):
                        score = max(5, min(100, round(base + rng.gauss(0, 6))))
                        grades.append(Grade(student=p.record, subject=subjects[name], term=term,
                                            assessment_type=kind, score=Decimal(score), max_score=Decimal(100)))
                        total += score * weight[kind.id]
                        weights += weight[kind.id]
                    scores[name] = total / weights
                if not finished or not scores:
                    continue
                for name, score in scores.items():
                    crng = random.Random(f"{p.record.id}-{term.id}-{name}")
                    entries.append(SubjectReport(
                        student=p.record, subject=subjects[name], term=term,
                        comment=crng.choice(SUBJECT_COMMENTS[band(score)]), effort=str(crng.choice([1, 2, 2, 3])),
                        target=level_for(min(100, score + 10), "igcse" if g >= 12 else "igcse9") or "",
                    ))
                best, weakest = max(scores, key=scores.get), min(scores, key=scores.get)
                done = timezone.make_aware(datetime.combine(term.end_date, time(15)))
                reports.append(StudentReport(
                    student=p.record, term=term, status="finalized", tone_used="warm",
                    progress_summary=f"Average {sum(scores.values()) / len(scores):.0f}%. "
                                     f"Strongest in {best}, weakest in {weakest}.",
                    report_comment=TEACHER_COMMENTS["warm"].format(name=p.record.first_name, best=best,
                                                                   weakest=weakest, subjects="subjects",
                                                                   term="term"),
                    principal_comment=PRINCIPAL_COMMENT.format(term="term"),
                    submitted_by=teachers[(g * 7 + ord(form)) % len(teachers)].user, submitted_at=done - timedelta(days=5),
                    finalized_by=principal.user, finalized_at=done - timedelta(days=2),
                    # The form they were in that year, as finalizing records it.
                    school_class=klass, class_name=f"Year {g} · {klass.name}", education_system="british",
                    grading_scale="igcse" if g >= 12 else "igcse9",
                ))
            Grade.objects.bulk_create(grades, batch_size=5000)
            SubjectReport.objects.bulk_create(entries, batch_size=5000)
            StudentReport.objects.bulk_create(reports, batch_size=2000)
            grade_count += len(grades)
            report_count += len(reports)

    # --- this school year's registers so far
    active = [p for g in roll.values() for p in g]
    records = []
    day = years[-1][1][0].start_date
    while day < today:
        in_term = any(t.start_date <= day <= t.end_date for t in years[-1][1])
        if day.weekday() < 5 and in_term:
            for p in active:
                r = rng.random()
                status = "absent" if r < p.absent_rate else "late" if r < p.absent_rate + 0.03 else "present"
                records.append(AttendanceRecord(student=p.record, date=day, status=status))
        day += timedelta(days=1)
    AttendanceRecord.objects.bulk_create(records, batch_size=5000)

    # --- parents: about two thirds of current students, some with two children here
    linked = active[:]
    rng.shuffle(linked)
    # parent@ belongs to a Year 13 who has been here all five years, so their history is complete.
    veteran = next((p for p in roll[13] if p.joined == first_year), roll[13][0])
    linked.remove(veteran)
    linked.insert(0, veteran)
    parents = 0
    i = 0
    while i < len(linked) * 2 // 3:
        child = linked[i]
        kids = [child.record]
        if rng.random() < 0.12 and i + 1 < len(linked):
            i += 1
            sibling = linked[i].record
            sibling.last_name = child.record.last_name
            sibling.save(update_fields=["last_name"])
            kids.append(sibling)
        female = rng.random() < 0.6
        pname = f"{rng.choice(GIRLS if female else BOYS)} {child.record.last_name}"
        g = Guardian.objects.create(user=user("parent" if parents == 0 else f"parent{parents:04d}", pname),
                                    school=school, display_name=pname, relationship="mother" if female else "father",
                                    phone=f"+254 7{rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(100, 999)}")
        g.students.set(kids)
        parents += 1
        i += 1

    Announcement.objects.create(
        school=school, title=f"Welcome back for the {current.name}", audience="all_parents", status="published",
        created_by=principal.user, published_at=now - timedelta(days=20),
        body="Welcome back to a new school year. Reports for last year's terms are available to download in "
             "HouseMaster, and Year 7 and Year 12 parents' evenings are later this month.",
    )
    _support_concerns(school, leaders[1].user)
    from timetable.services import fill_demo

    lessons = fill_demo(school, rooms=60)
    from boarding.demo import fill_demo as fill_boarding

    boarders = fill_boarding(school, house_names=("Darwin House", "Austen House"))
    from admissions.demo import fill_demo as fill_admissions

    fill_admissions(school, DOMAIN)
    log_activity(school=school, actor=None, action="school.demo_created",
                 summary=f"Created {NAME} with {len(active)} current students and five years of history")
    return (f"Created {NAME}: {len(active)} current students in {len(forms)} forms, {len(leavers)} former students, "
            f"{len(teachers) + len(leaders)} staff, {parents} parents, {grade_count} marks, {report_count} report "
            f"cards over {sum(1 for _, ts in years for t in ts if t.start_date <= today)} terms, {len(records)} "
            f"register entries, {lessons} lessons on the timetable, {boarders} boarders. Log in as principal@{DOMAIN}, teacher@{DOMAIN} or parent@{DOMAIN}.")


def _joined_group(p, history, years):
    for index, (y, _) in enumerate(years):
        if y == p.joined:
            for g, ps in history[index].items():
                if any(q is p for q, _ in ps):
                    return g
    return 7


def _subjects_then(p, group):
    """What the student took in a given year group (their choices were made when they reached it)."""
    if group <= 9:
        return KS3
    if group <= 11:
        return GCSE_CORE + (p.options or GCSE_OPTIONS[:3])
    return p.a_levels or ["Mathematics", "Biology", "History"]


def _support_concerns(school, actor):
    """A few students already marked as needing support, so the page isn't empty."""
    from reporting.analytics import SchoolGrades
    from support.models import SupportConcern
    from support.services import warning_signs

    data = SchoolGrades(school, recent=True)
    term = data.term(None)
    found = warning_signs(data, term, list(data.students))
    plans = ["Weekly catch-up with the subject teacher; please check homework is done each evening.",
             "Small-group sessions twice a week, and a reading plan to follow at home.",
             "A mentor from the sixth form, and a review with parents at half term."]
    for k, (student_id, reasons) in enumerate(list(found.items())[:6]):
        SupportConcern.objects.create(
            school=school, student=data.students[student_id], term=term, status="open", source="auto",
            reasons=reasons, note="Marks have dipped this term and we would like to help early.",
            support_plan=plans[k % len(plans)], review_date=timezone.localdate() + timedelta(days=7 * (k - 1)),
            created_by=actor, created_by_name=f"{actor.first_name} {actor.last_name}",
        )
