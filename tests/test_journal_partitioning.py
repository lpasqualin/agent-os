"""Phase A1 tests — Journal Partitioning.

Proves:
1. New writes land in journal/YYYY/MM/{run_id}.json
2. list_runs() works across multiple partitions, newest-first
3. list_runs(limit=N) is respected
4. read_latest() still returns the most recently written record
5. find_record() locates a record by run_id across partitions
6. find_record_path() returns the correct filesystem path
7. stats() returns correct aggregate counts and coverage
8. export() JSON format produces valid output
9. export() CSV format produces valid output
10. export() --since / --until date filters work
11. Flat-file migration moves records into correct partitions
12. Migrated records are still queryable via list_runs()
13. write() failure is silent — never raises
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

import pytest

from agent_os.journal import ExecutionJournal, migrate_flat_to_partitioned
from agent_os.contracts.models import ExecutionJournalRecord


# ── Helpers ───────────────────────────────────────────────────

def _make_record(
    *,
    run_id: str | None = None,
    agent_id: str = "clawbot",
    status: str = "succeeded",
    requested_at: datetime | None = None,
    capability: str = "tasks.create",
) -> ExecutionJournalRecord:
    now = requested_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    rid = run_id or f"run_{uuid.uuid4().hex[:8]}"
    return ExecutionJournalRecord(
        journal_id=uuid.uuid4().hex,
        run_id=rid,
        agent_id=agent_id,
        capability=capability,
        runtime_target="mock",
        requested_at=now,
        finished_at=now + timedelta(milliseconds=50),
        status=status,
        lifecycle_trace=[],
    )


@pytest.fixture()
def jdir(tmp_path) -> Path:
    return tmp_path / "journal"


# ── 1. Partitioned write path ─────────────────────────────────

class TestPartitionedWrites:

    def test_write_creates_yyyy_mm_partition(self, jdir):
        j = ExecutionJournal(jdir)
        rec = _make_record(requested_at=datetime(2026, 4, 15, tzinfo=timezone.utc))
        j.write(rec)

        expected = jdir / "2026" / "04" / f"{rec.run_id}.json"
        assert expected.exists(), f"Expected partition file at {expected}"

    def test_write_creates_flat_compat_file(self, jdir):
        j = ExecutionJournal(jdir)
        rec = _make_record()
        j.write(rec)

        flat = jdir / f"{rec.run_id}.json"
        partitioned = j.find_record_path(rec.run_id)

        assert flat.exists()
        assert partitioned is not None
        assert partitioned.exists()

    def test_write_into_past_partition(self, jdir):
        j = ExecutionJournal(jdir)
        rec = _make_record(requested_at=datetime(2025, 3, 15, tzinfo=timezone.utc))
        j.write(rec)

        assert (jdir / "2025" / "03" / f"{rec.run_id}.json").exists()

    def test_write_into_different_months_creates_separate_dirs(self, jdir):
        j = ExecutionJournal(jdir)
        jan = _make_record(requested_at=datetime(2026, 1, 10, tzinfo=timezone.utc))
        feb = _make_record(requested_at=datetime(2026, 2, 10, tzinfo=timezone.utc))
        j.write(jan)
        j.write(feb)

        assert (jdir / "2026" / "01").is_dir()
        assert (jdir / "2026" / "02").is_dir()

    def test_record_content_survives_round_trip(self, jdir):
        j = ExecutionJournal(jdir)
        rec = _make_record(status="failed", requested_at=datetime(2026, 4, 1, tzinfo=timezone.utc))
        j.write(rec)

        path = jdir / "2026" / "04" / f"{rec.run_id}.json"
        loaded = ExecutionJournalRecord.model_validate_json(path.read_text())
        assert loaded.run_id == rec.run_id
        assert loaded.status == rec.status

    def test_write_failure_is_silent(self, tmp_path):
        """A journal write failure must never propagate to the caller."""
        blocked = tmp_path / "file_not_dir"
        blocked.write_text("I am a file")
        j = ExecutionJournal(blocked / "journal")  # parent is a file → mkdir fails
        # Must not raise
        j.write(_make_record())


# ── 2. list_runs() across partitions ─────────────────────────

class TestListRuns:

    def test_list_runs_across_multiple_months(self, jdir):
        j = ExecutionJournal(jdir)
        months = [
            datetime(2025, 11, 1, tzinfo=timezone.utc),
            datetime(2025, 12, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 2, 1, tzinfo=timezone.utc),
        ]
        ids = []
        for m in months:
            rec = _make_record(requested_at=m)
            ids.append(rec.run_id)
            j.write(rec)

        rows = j.list_runs(limit=100)
        found_ids = {r["run_id"] for r in rows}
        assert set(ids) == found_ids

    def test_list_runs_newest_first(self, jdir):
        j = ExecutionJournal(jdir)
        for month in [1, 2, 3, 4]:
            j.write(_make_record(requested_at=datetime(2026, month, 15, tzinfo=timezone.utc)))

        rows = j.list_runs(limit=10)
        timestamps = [r["requested_at"] for r in rows]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_list_runs_respects_limit(self, jdir):
        j = ExecutionJournal(jdir)
        for i in range(10):
            j.write(_make_record(requested_at=datetime(2026, 1, i + 1, tzinfo=timezone.utc)))

        rows = j.list_runs(limit=3)
        assert len(rows) == 3

    def test_list_runs_empty_journal(self, jdir):
        j = ExecutionJournal(jdir)
        assert j.list_runs() == []

    def test_list_runs_row_schema(self, jdir):
        j = ExecutionJournal(jdir)
        j.write(_make_record())

        rows = j.list_runs()
        assert len(rows) == 1
        row = rows[0]
        for key in ("run_id", "status", "agent_id", "capability", "requested_at", "finished_at"):
            assert key in row, f"Missing expected key: {key}"


# ── 3. read_latest() ─────────────────────────────────────────

class TestReadLatest:

    def test_read_latest_returns_most_recent(self, jdir):
        j = ExecutionJournal(jdir)
        older = _make_record(requested_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        newer = _make_record(requested_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        j.write(older)
        j.write(newer)

        latest = j.read_latest()
        assert latest is not None
        assert latest.run_id == newer.run_id

    def test_read_latest_returns_none_when_empty(self, jdir):
        j = ExecutionJournal(jdir)
        assert j.read_latest() is None

    def test_read_latest_across_year_boundary(self, jdir):
        j = ExecutionJournal(jdir)
        y2025 = _make_record(requested_at=datetime(2025, 12, 31, tzinfo=timezone.utc))
        y2026 = _make_record(requested_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        j.write(y2025)
        j.write(y2026)

        latest = j.read_latest()
        assert latest.run_id == y2026.run_id


# ── 4. find_record() and find_record_path() ───────────────────

class TestFindRecord:

    def test_find_record_locates_by_run_id(self, jdir):
        j = ExecutionJournal(jdir)
        rec = _make_record(requested_at=datetime(2025, 6, 15, tzinfo=timezone.utc))
        j.write(rec)

        found = j.find_record(rec.run_id)
        assert found is not None
        assert found.run_id == rec.run_id

    def test_find_record_returns_none_if_missing(self, jdir):
        j = ExecutionJournal(jdir)
        assert j.find_record("run_doesnotexist") is None

    def test_find_record_across_partitions(self, jdir):
        j = ExecutionJournal(jdir)
        jan = _make_record(requested_at=datetime(2026, 1, 5, tzinfo=timezone.utc))
        mar = _make_record(requested_at=datetime(2026, 3, 5, tzinfo=timezone.utc))
        j.write(jan)
        j.write(mar)

        assert j.find_record(jan.run_id).run_id == jan.run_id
        assert j.find_record(mar.run_id).run_id == mar.run_id

    def test_find_record_path_returns_correct_path(self, jdir):
        j = ExecutionJournal(jdir)
        rec = _make_record(requested_at=datetime(2026, 4, 10, tzinfo=timezone.utc))
        j.write(rec)

        p = j.find_record_path(rec.run_id)
        assert p is not None
        assert p.exists()
        assert p.stem == rec.run_id

    def test_find_record_path_returns_none_if_missing(self, jdir):
        j = ExecutionJournal(jdir)
        assert j.find_record_path("run_ghost") is None


# ── 5. stats() ────────────────────────────────────────────────

class TestStats:

    def test_stats_total_runs(self, jdir):
        j = ExecutionJournal(jdir)
        for _ in range(5):
            j.write(_make_record())

        s = j.stats()
        assert s["total_runs"] == 5

    def test_stats_empty_journal(self, jdir):
        j = ExecutionJournal(jdir)
        s = j.stats()
        assert s["total_runs"] == 0
        assert s["by_status"] == {}

    def test_stats_by_status(self, jdir):
        j = ExecutionJournal(jdir)
        for _ in range(3):
            j.write(_make_record(status="succeeded"))
        for _ in range(2):
            j.write(_make_record(status="failed"))
        j.write(_make_record(status="rejected"))

        s = j.stats()
        assert s["by_status"]["succeeded"] == 3
        assert s["by_status"]["failed"] == 2
        assert s["by_status"]["rejected"] == 1

    def test_stats_date_range(self, jdir):
        j = ExecutionJournal(jdir)
        j.write(_make_record(requested_at=datetime(2025, 6, 1, tzinfo=timezone.utc)))
        j.write(_make_record(requested_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        j.write(_make_record(requested_at=datetime(2026, 3, 1, tzinfo=timezone.utc)))

        s = j.stats()
        assert s["earliest"] is not None
        assert s["latest"] is not None
        assert s["earliest"] <= s["latest"]

    def test_stats_disk_bytes_positive(self, jdir):
        j = ExecutionJournal(jdir)
        j.write(_make_record())
        assert j.stats()["disk_bytes"] > 0


# ── 6. export() JSON ─────────────────────────────────────────

class TestExportJSON:

    def test_export_json_produces_list(self, jdir):
        j = ExecutionJournal(jdir)
        j.write(_make_record())
        j.write(_make_record())

        records = json.loads(j.export(fmt="json"))
        assert isinstance(records, list)
        assert len(records) == 2

    def test_export_json_since_filter(self, jdir):
        j = ExecutionJournal(jdir)
        old = _make_record(requested_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
        new = _make_record(requested_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        j.write(old)
        j.write(new)

        records = json.loads(j.export(fmt="json", since=date(2026, 1, 1)))
        assert len(records) == 1
        assert records[0]["run_id"] == new.run_id

    def test_export_json_until_filter(self, jdir):
        j = ExecutionJournal(jdir)
        old = _make_record(requested_at=datetime(2025, 6, 1, tzinfo=timezone.utc))
        new = _make_record(requested_at=datetime(2026, 4, 1, tzinfo=timezone.utc))
        j.write(old)
        j.write(new)

        records = json.loads(j.export(fmt="json", until=date(2025, 12, 31)))
        assert len(records) == 1
        assert records[0]["run_id"] == old.run_id

    def test_export_json_both_filters(self, jdir):
        j = ExecutionJournal(jdir)
        for month in [1, 2, 3, 4, 5]:
            j.write(_make_record(requested_at=datetime(2026, month, 1, tzinfo=timezone.utc)))

        records = json.loads(j.export(
            fmt="json",
            since=date(2026, 2, 1),
            until=date(2026, 4, 30),
        ))
        assert len(records) == 3  # Feb, Mar, Apr


# ── 7. export() CSV ──────────────────────────────────────────

class TestExportCSV:

    def test_export_csv_has_header(self, jdir):
        j = ExecutionJournal(jdir)
        j.write(_make_record())

        out = j.export(fmt="csv")
        reader = csv.DictReader(io.StringIO(out))
        assert reader.fieldnames is not None
        assert "run_id" in reader.fieldnames
        assert "status" in reader.fieldnames

    def test_export_csv_row_count(self, jdir):
        j = ExecutionJournal(jdir)
        for _ in range(4):
            j.write(_make_record())

        out = j.export(fmt="csv")
        rows = list(csv.DictReader(io.StringIO(out)))
        assert len(rows) == 4

    def test_export_csv_empty_journal(self, jdir):
        j = ExecutionJournal(jdir)
        out = j.export(fmt="csv")
        assert out == "" or "run_id" in out


# ── 8. Migration ─────────────────────────────────────────────

class TestMigration:

    def test_migrate_moves_flat_files_to_partitions(self, jdir):
        jdir.mkdir(parents=True)
        rec1 = _make_record(requested_at=datetime(2025, 11, 15, tzinfo=timezone.utc))
        rec2 = _make_record(requested_at=datetime(2026, 2, 20, tzinfo=timezone.utc))

        (jdir / f"{rec1.run_id}.json").write_text(rec1.model_dump_json(indent=2))
        (jdir / f"{rec2.run_id}.json").write_text(rec2.model_dump_json(indent=2))

        report = migrate_flat_to_partitioned(jdir)

        assert report["moved"] == 2
        assert report["errors"] == 0
        assert not (jdir / f"{rec1.run_id}.json").exists()
        assert not (jdir / f"{rec2.run_id}.json").exists()
        assert (jdir / "2025" / "11" / f"{rec1.run_id}.json").exists()
        assert (jdir / "2026" / "02" / f"{rec2.run_id}.json").exists()

    def test_migrate_records_still_queryable_after_migration(self, jdir):
        jdir.mkdir(parents=True)
        rec = _make_record(requested_at=datetime(2026, 1, 5, tzinfo=timezone.utc))
        (jdir / f"{rec.run_id}.json").write_text(rec.model_dump_json(indent=2))

        migrate_flat_to_partitioned(jdir)

        j = ExecutionJournal(jdir)
        rows = j.list_runs()
        assert any(r["run_id"] == rec.run_id for r in rows)

    def test_migrate_skips_non_json_files(self, jdir):
        jdir.mkdir(parents=True)
        (jdir / "README.txt").write_text("not a record")

        report = migrate_flat_to_partitioned(jdir)

        assert report["moved"] == 0
        assert (jdir / "README.txt").exists()

    def test_migrate_skips_files_missing_requested_at(self, jdir):
        jdir.mkdir(parents=True)
        bad = {"run_id": "run_bad", "status": "succeeded"}
        (jdir / "run_bad.json").write_text(json.dumps(bad))

        report = migrate_flat_to_partitioned(jdir)

        assert report["errors"] == 1
        assert (jdir / "run_bad.json").exists()

    def test_migrate_idempotent_on_already_partitioned(self, jdir):
        j = ExecutionJournal(jdir)
        rec = _make_record(requested_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
        j.write(rec)

        report = migrate_flat_to_partitioned(jdir)

        assert report["moved"] == 0
        assert j.find_record(rec.run_id) is not None

