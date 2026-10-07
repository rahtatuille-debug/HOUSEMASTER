"""
Boarding houses and random bed allocation (owner's request, 2026-10-07):
- an admin allocates boarders to a boarding house;
- house staff (or an admin) fill a house's free beds at random with its allocated boarders who have no bed.
"""
import random

from activity.models import ActivityLog
from students.models import Student

from .models import Bed, Dorm, HouseAllocation
from .services import release_boarders
from .test_safeguarding import Fixture


class AllocationTests(Fixture):
    def new_boarder(self, name, school=None, klass=None, **extra):
        return Student.objects.create(school=school or self.school_a, first_name=name, last_name="N",
                                      school_class=klass or self.c2, mode_of_learning="boarding", **extra)

    def allocate(self, students, house, client=None):
        return (client or self.admin).post("/api/boarding/allocations/", {
            "students": [s.id for s in students], "house": house.id if house else None}, format="json")

    def test_admin_allocates_boarders_to_a_house(self):
        dee, eve = self.new_boarder("Dee"), self.new_boarder("Eve")
        response = self.allocate([dee, eve], self.house)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["allocated"], 2)
        self.assertEqual(set(HouseAllocation.objects.filter(house=self.house).values_list("student_id", flat=True)),
                         {dee.id, eve.id})
        self.assertTrue(ActivityLog.objects.filter(action="boarding.house", target_id=dee.id,
                                                   summary__icontains="Uhuru House").exists())

    def test_the_list_shows_each_boarders_house_and_bed(self):
        dee = self.new_boarder("Dee")
        self.allocate([dee], self.house)
        rows = {r["name"]: r for r in self.admin.get("/api/boarding/allocations/").data}
        self.assertEqual((rows["Dee N"]["house"], rows["Dee N"]["bed"]), ("Uhuru House", ""))
        # Boarders placed in a bed before allocation existed count as that house's.
        self.assertEqual((rows["Amina K"]["house"], rows["Amina K"]["bed"]), ("Uhuru House", "Dorm A Bed 1"))
        self.assertNotIn("Day N", rows)  # day students aren't boarders

    def test_moving_to_another_house_gives_up_the_old_bed(self):
        self.allocate([self.amina], self.other_house)
        self.assertFalse(Bed.objects.filter(student=self.amina).exists())
        self.assertEqual(self.amina.house_allocation.house, self.other_house)
        self.assertTrue(ActivityLog.objects.filter(action="boarding.house", target_id=self.amina.id,
                                                   summary__icontains="gave up").exists())

    def test_only_admins_allocate_and_only_their_schools_students(self):
        dee = self.new_boarder("Dee")
        self.assertEqual(self.allocate([dee], self.house, client=self.matron).status_code, 403)
        outsider = self.new_boarder("Zed", school=self.school_b, klass=None)
        response = self.allocate([outsider], self.house)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(HouseAllocation.objects.filter(student=outsider).exists())

    def test_day_students_and_leavers_are_refused(self):
        day = Student.objects.create(school=self.school_a, first_name="Day", last_name="N", school_class=self.c2)
        left = self.new_boarder("Gone", is_active=False)
        self.assertEqual(self.allocate([day], self.house).status_code, 400)
        self.assertEqual(self.allocate([left], self.house).status_code, 400)

    def test_an_archived_house_is_refused(self):
        self.other_house.is_archived = True
        self.other_house.save()
        self.assertEqual(self.allocate([self.new_boarder("Dee")], self.other_house).status_code, 400)

    def test_putting_a_boarder_in_a_bed_sets_their_house(self):
        dee = self.new_boarder("Dee")
        self.allocate([dee], self.other_house)
        response = self.matron.post(f"/api/boarding/beds/{self.beds[3].id}/", {"student": dee.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        dee.house_allocation.refresh_from_db()
        self.assertEqual(dee.house_allocation.house, self.house)

    def test_leaving_the_school_clears_the_house(self):
        dee = self.new_boarder("Dee")
        self.allocate([dee], self.house)
        release_boarders([dee.id], "left_school")
        self.assertFalse(HouseAllocation.objects.filter(student=dee).exists())


class RandomBedTests(Fixture):
    def setUp(self):
        super().setUp()
        self.dorm_b = Dorm.objects.create(house=self.house, name="Dorm B")
        self.free = [self.beds[3]] + [Bed.objects.create(dorm=self.dorm_b, name=f"Bed {n}") for n in (1, 2)]
        self.waiting = [Student.objects.create(school=self.school_a, first_name=n, last_name="W", school_class=self.c2,
                                               mode_of_learning="boarding") for n in ("Dee", "Eve")]
        for s in self.waiting:
            HouseAllocation.objects.create(student=s, house=self.house)
        # Allocated elsewhere: never put in this house's beds.
        self.elsewhere = Student.objects.create(school=self.school_a, first_name="Fay", last_name="W",
                                                school_class=self.c2, mode_of_learning="boarding")
        HouseAllocation.objects.create(student=self.elsewhere, house=self.other_house)

    def fill(self, client=None, house=None):
        return (client or self.matron).post(f"/api/boarding/houses/{(house or self.house).id}/fill-beds/", {},
                                            format="json")

    def test_house_staff_fill_free_beds_with_the_houses_waiting_boarders(self):
        response = self.fill()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["placed"]), 2)
        self.assertEqual((response.data["still_waiting"], response.data["beds_left"]), (0, 1))
        for s in self.waiting:
            self.assertEqual(Bed.objects.get(student=s).dorm.house, self.house)
        self.assertFalse(Bed.objects.filter(student=self.elsewhere).exists())
        # Nobody who already had a bed was moved.
        self.assertEqual(Bed.objects.get(student=self.amina), self.beds[0])
        self.assertEqual(ActivityLog.objects.filter(action="boarding.bed", summary__icontains="at random").count(), 2)

    def test_the_draw_is_random(self):
        seen = set()
        for seed in range(12):
            Bed.objects.filter(student__in=self.waiting).update(student=None)
            random.seed(seed)
            self.fill()
            seen.add(Bed.objects.get(student=self.waiting[0]).id)
        self.assertGreater(len(seen), 1)

    def test_more_boarders_than_beds_leaves_the_rest_waiting(self):
        more = [Student.objects.create(school=self.school_a, first_name=f"X{n}", last_name="W", school_class=self.c2,
                                       mode_of_learning="boarding") for n in range(3)]
        for s in more:
            HouseAllocation.objects.create(student=s, house=self.house)
        response = self.fill()
        self.assertEqual((len(response.data["placed"]), response.data["still_waiting"], response.data["beds_left"]),
                         (3, 2, 0))

    def test_a_bed_held_by_a_leaver_counts_as_free(self):
        gone = Student.objects.create(school=self.school_a, first_name="Gone", last_name="W", school_class=self.c2,
                                      mode_of_learning="boarding", is_active=False)
        Bed.objects.filter(pk=self.free[1].pk).update(student=gone)
        Bed.objects.filter(pk__in=[self.free[0].pk, self.free[2].pk]).delete()
        response = self.fill()
        self.assertEqual(len(response.data["placed"]), 1)
        self.assertNotEqual(Bed.objects.get(pk=self.free[1].pk).student, gone)

    def test_staff_of_another_house_and_other_schools_cannot(self):
        self.assertEqual(self.fill(client=self.matron, house=self.other_house).status_code, 404)
        self.assertEqual(self.fill(client=self.plain).status_code, 403)
        self.assertEqual(self.fill(client=self.client_b).status_code, 404)
        self.assertFalse(Bed.objects.filter(student__in=self.waiting).exists())

    def test_house_list_shows_who_is_waiting(self):
        house = next(h for h in self.matron.get("/api/boarding/houses/").data if h["id"] == self.house.id)
        self.assertEqual((house["allocated_waiting"], house["beds_free"]), (2, 3))
