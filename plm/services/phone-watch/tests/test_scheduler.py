from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from phone_watch.scheduler import next_run


class SchedulerTests(unittest.TestCase):
    def test_next_run_uses_shanghai_0800(self) -> None:
        zone = ZoneInfo("Asia/Shanghai")
        self.assertEqual(next_run(datetime(2026,10,9,7,30,tzinfo=zone)), datetime(2026,10,9,8,0,tzinfo=zone))
        self.assertEqual(next_run(datetime(2026,10,9,8,0,tzinfo=zone)), datetime(2026,10,10,8,0,tzinfo=zone))


if __name__ == "__main__":
    unittest.main()
