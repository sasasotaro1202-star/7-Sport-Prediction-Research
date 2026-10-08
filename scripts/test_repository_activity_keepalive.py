from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/repository_activity_keepalive.yml"

text = WORKFLOW.read_text(encoding="utf-8")

assert 'cron: "17 3 1,15 * *"' in text
assert "workflow_dispatch:" in text
assert "workflow_run:" not in text
assert "permissions:\n  contents: write" in text
assert "actions: write" not in text
assert "group: repository-activity-keepalive" in text
assert "cancel-in-progress: true" in text
assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in text
assert "ops/automation/heartbeat.json" in text
MARKER_WRITER = ROOT / "scripts/write_keepalive_marker.py"
marker_writer = MARKER_WRITER.read_text(encoding="utf-8")
assert '"purpose": "repository_activity_keepalive"' in marker_writer
assert "name: Repository Activity Keepalive" in text
assert "without touching production/model artifacts" in text
assert "production/model artifacts" in text
assert "max_attempts=3" in text
assert "KEEPALIVE_RETRY" in text
assert "git push origin HEAD:main" in text
assert "git push --force" not in text
assert "git push -f" not in text
assert 'git reset --hard "$latest_main"' in text
assert "KEEPALIVE_GENERATED_AT" in text
assert "KEEPALIVE_BASE_SHA" in text

print("REPOSITORY_ACTIVITY_KEEPALIVE_CONTRACT=PASS")
