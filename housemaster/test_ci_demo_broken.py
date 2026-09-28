"""Deliberately failing test, to show CI turns red. This branch is deleted afterwards."""
from django.test import SimpleTestCase


class DeliberatelyBrokenTest(SimpleTestCase):
    def test_ci_catches_a_failure(self):
        self.assertEqual(1 + 1, 3)
