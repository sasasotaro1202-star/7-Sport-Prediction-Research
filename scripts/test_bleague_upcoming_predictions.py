from datetime import datetime, timezone
from src.bleague_upcoming_predictions import parse_detail, to_utc

HTML = """
<html>
<head><title>りそなグループ B.LEAGUE 2026-27 B.LEAGUE PREMIER リーグ戦 2026/10/03 横浜BC VS 信州</title></head>
<body>
2026.10.03（土）15:05 TIP OFF
横浜ビー・コルセアーズ
横浜BC
VS
信州ブレイブウォリアーズ
信州
B.PREMIER
</body>
</html>
"""

x = parse_detail(HTML, "https://www.bleague.jp/game_detail/?ScheduleKey=506411")
assert x is not None
assert x["home"]
assert x["away"]
assert x["competition"] == "B.PREMIER"
assert to_utc(x["date"], x["time"]).startswith("2026-10-03T06:05:00")

# A modification/metadata timestamp alone must not invent game time.
assert to_utc("not-a-date", "15:05") is None
print("BLEAGUE_UPCOMING_PREDICTIONS_SMOKE=PASS")
