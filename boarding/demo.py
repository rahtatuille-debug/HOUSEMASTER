"""Boarding for demo schools: houses, beds, house staff, leave, roll calls and sick bay visits."""
import random
from datetime import datetime, time, timedelta

from django.utils import timezone

from accounts.models import Profile
from students.localtime import school_localdate
from students.models import Student

from .models import Bed, BoardingHouse, Dorm, LeaveRequest, RollCall, RollCallEntry, SickBayVisit

COMPLAINTS = [("Headache", "Paracetamol 500 mg, rest for an hour."), ("Stomach ache", "Rest and water; ate a light lunch."),
              ("Fever, 38.4°C", "Paracetamol; stayed overnight and was watched."), ("Twisted ankle in games",
              "Ice pack and bandage."), ("Cold and sore throat", "Lozenges and rest."), ("Cut finger", "Cleaned and plaster.")]


def fill_demo(school, share=0.0, house_names=("Kilimanjaro House", "Elgon House")):
    """Give a demo school boarding. With `share`, that fraction of students becomes boarders first.
    Returns the number of boarders placed in beds."""
    rng = random.Random(f"boarding-{school.id}")
    tz_now = timezone.now()
    today = school_localdate(school)
    students = list(Student.objects.filter(school=school, is_active=True).order_by("id"))
    if share:
        chosen = {s.id for s in rng.sample(students, int(len(students) * share))}
        Student.objects.filter(id__in=chosen).update(mode_of_learning="boarding")
    boarders = [s for s in Student.objects.filter(school=school, is_active=True, mode_of_learning="boarding")
                .order_by("gender", "id")]
    if not boarders:
        return 0
    staff = list(Profile.objects.filter(school=school, role="teacher", user__is_active=True).order_by("id"))
    halves = {"female": [s for s in boarders if s.gender == "female"],
              "male": [s for s in boarders if s.gender != "female"]}
    placed = 0
    for n, (key, group) in enumerate(halves.items()):
        if not group:
            continue
        house = BoardingHouse.objects.create(school=school, name=house_names[n % len(house_names)])
        house.staff.set(staff[n * 2: n * 2 + 2])
        per_dorm = 12
        dorms = [Dorm.objects.create(house=house, name=f"Dorm {chr(65 + d)}")
                 for d in range((len(group) + per_dorm) // per_dorm)]
        beds = []
        for d, dorm in enumerate(dorms):
            beds += [Bed(dorm=dorm, name=f"Bed {b + 1}") for b in range(per_dorm)]
        for bed, student in zip(beds, group):
            bed.student = student
        Bed.objects.bulk_create(beds)
        placed += len(group)

        # Leave: a few waiting, some approved ahead, two out now, and past weekends.
        def leave(student, status, start_days, nights, kind="weekend", **extra):
            leaving = timezone.make_aware(datetime.combine(today + timedelta(days=start_days), time(16)))
            LeaveRequest.objects.create(
                school=school, student=student, kind=kind, leaving_at=leaving,
                returning_at=leaving + timedelta(days=nights, hours=2), status=status,
                reason={"weekend": "Family weekend at home.", "appointment": "Dentist appointment in town.",
                        "exeat": "Cousin's wedding."}.get(kind, ""),
                collected_by=f"{rng.choice(['Mother', 'Father', 'Aunt', 'Uncle'])} ({student.last_name})",
                requested_by_name="Parent", **extra)
        for s in group[:2]:
            leave(s, "requested", 4, 2)
        for s in group[2:5]:
            leave(s, "approved", 4, 2, decided_by_name=house.staff.first().name if house.staff.exists() else "",
                  decided_at=tz_now)
        for s in group[5:7]:
            leave(s, "out", -1, 2, kind="exeat", signed_out_at=tz_now - timedelta(days=1), signed_out_by_name="Matron")
        for s in rng.sample(group, min(8, len(group))):
            leave(s, "returned", -rng.randint(8, 40), 2, signed_out_at=tz_now - timedelta(days=20),
                  signed_in_at=tz_now - timedelta(days=18), signed_out_by_name="Matron", signed_in_by_name="Matron")

        # Sick bay: one in now, and some earlier visits.
        in_sick_bay = group[7] if len(group) > 7 else None
        if in_sick_bay:
            SickBayVisit.objects.create(school=school, student=in_sick_bay, checked_in_at=tz_now - timedelta(hours=3),
                                        checked_in_by_name="Nurse Atieno", complaint="Fever, 38.4°C",
                                        treatment="Paracetamol 500 mg; resting.",
                                        parents_told_at=tz_now - timedelta(hours=2),
                                        parents_told_how="Phoned mother")
        for s in rng.sample(group, min(6, len(group))):
            if s == in_sick_bay:
                continue
            complaint, treatment = rng.choice(COMPLAINTS)
            start = tz_now - timedelta(days=rng.randint(2, 50), hours=rng.randint(0, 8))
            SickBayVisit.objects.create(school=school, student=s, checked_in_at=start, checked_in_by_name="Nurse Atieno",
                                        complaint=complaint, treatment=treatment,
                                        checked_out_at=start + timedelta(hours=rng.randint(1, 20)),
                                        checked_out_by_name="Nurse Atieno", outcome="back")

        # Roll calls for the last three evenings and nights; last night one boarder was missing.
        away = {s.id for s in group[5:7]} | ({in_sick_bay.id} if in_sick_bay else set())
        for back in (3, 2, 1):
            for session in ("evening", "night"):
                roll = RollCall.objects.create(house=house, date=today - timedelta(days=back), session=session,
                                               taken_by_name="Matron", completed_at=tz_now - timedelta(days=back))
                entries = []
                for s in group:
                    status = "present"
                    if s.id in away:
                        status = "sick_bay" if in_sick_bay and s.id == in_sick_bay.id else "on_leave"
                    entries.append(RollCallEntry(roll_call=roll, student=s, status=status))
                in_house = [e for e in entries if e.status == "present"]
                if back == 1 and session == "night" and in_house:
                    in_house[-1].status = "missing"
                    in_house[-1].note = "Not in the dorm at lights out."
                RollCallEntry.objects.bulk_create(entries)
    return placed
