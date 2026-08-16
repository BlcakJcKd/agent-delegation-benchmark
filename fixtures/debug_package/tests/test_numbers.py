import unittest

from calcpack import clamp, mean, moving_average, slugify


class NumberTests(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(mean([2, 4, 6]), 4)


    def test_clamp_inside_and_outside(self):
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-1, 0, 10), 0)
        self.assertEqual(clamp(11, 0, 10), 10)


    def test_moving_average_has_complete_windows(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])


    def test_moving_average_rejects_zero_window(self):
        with self.assertRaises(ValueError):
            moving_average([1, 2], 0)


    def test_slugify(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")
