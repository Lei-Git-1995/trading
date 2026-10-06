import unittest
import pandas as pd

from stock_selector.indicators.pattern_recognition import detect_pattern


def frame(values):
    return pd.DataFrame({"收盘": values})


class PatternRecognitionTests(unittest.TestCase):
    def test_double_bottom(self):
        values = [12, 11, 10, 11, 12, 11.8, 10.1, 11.5, 13, 13.5, 13.8, 14]
        result = detect_pattern(frame(values), "double_bottom", order=1, min_separation=2)
        self.assertTrue(result["matched"])


    def test_double_top(self):
        values = [10, 11, 12, 11, 10, 10.2, 12.1, 11, 10, 9.5, 9.2, 9]
        result = detect_pattern(frame(values), "double_top", order=1, min_separation=2)
        self.assertTrue(result["matched"])


    def test_head_shoulders_and_invalid_history(self):
        values = [10, 12, 10, 14, 10, 12.1, 10, 9.5, 9.2, 9, 8.8, 8.5]
        result = detect_pattern(frame(values), "head_shoulders", order=1, min_separation=1)
        self.assertTrue(result["matched"])
        self.assertFalse(detect_pattern(frame([1, 2, 1]), "triangle")["matched"])


    def test_triangle_and_rectangle(self):
        triangle = [10, 10.5, 11, 10.2, 10.8, 10.4, 10.6, 10.5, 10.4, 10.5,
                    10.3, 10.4, 10.2, 10.3, 10.1, 10.2, 10, 10.1, 9.9, 10]
        self.assertEqual(
            set(detect_pattern(frame(triangle), "triangle", order=1)),
            {"matched", "pattern", "reason", "metrics"})
        rectangle = [10, 10.5, 10.1, 10.4, 10.0, 10.3] * 5
        self.assertEqual(
            set(detect_pattern(frame(rectangle), "rectangle", order=1)),
            {"matched", "pattern", "reason", "metrics"})


if __name__ == '__main__':
    unittest.main()
