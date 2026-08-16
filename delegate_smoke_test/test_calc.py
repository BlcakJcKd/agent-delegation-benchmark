import unittest

from calc import average


class AverageTests(unittest.TestCase):
    def test_average_of_two_and_four_is_three(self):
        self.assertEqual(average([2, 4]), 3)


if __name__ == "__main__":
    unittest.main()
