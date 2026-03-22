"""
Tests for the Disaster Recovery Manager.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from polyclaw.dr.recovery import (
    DisasterRecoveryManager,
    DRRecoveryReport,
    DRSnapshotInfo,
)


class TestDRSnapshotInfo:
    """Tests for DRSnapshotInfo dataclass."""

    def test_snapshot_info_creation(self):
        now = datetime.now(timezone.utc)
        snap = DRSnapshotInfo(
            snapshot_id="snap-12345",
            db_instance_identifier="polyclaw-db",
            snapshot_create_time=now,
            status="available",
            encrypted=True,
            allocated_storage_gb=20,
        )
        assert snap.snapshot_id == "snap-12345"
        assert snap.status == "available"
        assert snap.encrypted is True


class TestDRRecoveryReport:
    """Tests for DRRecoveryReport dataclass."""

    def test_report_success(self):
        started = datetime.now(timezone.utc)
        completed = datetime.now(timezone.utc)
        report = DRRecoveryReport(
            operation="restore_from_snapshot",
            started_at=started,
            completed_at=completed,
            success=True,
            message="Restore succeeded",
            details={"snapshot_id": "snap-123"},
        )
        assert report.success is True
        assert report.operation == "restore_from_snapshot"
        assert report.completed_at is not None

    def test_report_failure(self):
        started = datetime.now(timezone.utc)
        report = DRRecoveryReport(
            operation="restore_from_snapshot",
            started_at=started,
            completed_at=started,
            success=False,
            message="Restore failed",
            details={},
        )
        assert report.success is False


class TestDisasterRecoveryManager:
    """Tests for DisasterRecoveryManager."""

    def test_init_default_region(self):
        manager = DisasterRecoveryManager()
        assert manager.region == "us-east-1"
        assert manager.db_instance_id == "polyclaw-db"

    def test_init_custom_params(self):
        manager = DisasterRecoveryManager(
            region="us-west-2",
            db_instance_id="polyclaw-db-prod",
        )
        assert manager.region == "us-west-2"
        assert manager.db_instance_id == "polyclaw-db-prod"

    def test_log_audit_no_session_factory(self):
        """When no audit session factory is provided, _log_audit should not raise."""
        manager = DisasterRecoveryManager(audit_session_factory=None)
        # Should not raise
        manager._log_audit("test_action", "test_payload", "ok")

    def test_log_audit_with_session_factory(self):
        """When audit session factory is provided, _log_audit should log to DB."""
        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)

        manager = DisasterRecoveryManager(audit_session_factory=factory)
        manager._log_audit("dr_test", "test_operation", "ok")

        factory.assert_called_once()
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    # -------------------------------------------------------------------------
    # list_available_snapshots tests
    # -------------------------------------------------------------------------

    @patch("polyclaw.dr.recovery.boto3")
    def test_list_available_snapshots(self, mock_boto3):
        """Should return sorted snapshots from the last N days."""
        mock_page = {
            "DBSnapshots": [
                {
                    "DBSnapshotIdentifier": "snap-old",
                    "DBInstanceIdentifier": "polyclaw-db",
                    "SnapshotCreateTime": datetime(2026, 3, 19, 0, 0, 0, tzinfo=timezone.utc),
                    "Status": "available",
                    "Encrypted": True,
                    "AllocatedStorage": 20,
                },
                {
                    "DBSnapshotIdentifier": "snap-recent",
                    "DBInstanceIdentifier": "polyclaw-db",
                    "SnapshotCreateTime": datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc),
                    "Status": "available",
                    "Encrypted": True,
                    "AllocatedStorage": 20,
                },
                {
                    "DBSnapshotIdentifier": "snap-older-than-cutoff",
                    "DBInstanceIdentifier": "polyclaw-db",
                    "SnapshotCreateTime": datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "Status": "available",
                    "Encrypted": True,
                    "AllocatedStorage": 20,
                },
            ]
        }

        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_page]
        mock_boto3.client.return_value.get_paginator.return_value = mock_paginator

        manager = DisasterRecoveryManager()
        snapshots = manager.list_available_snapshots(days=7)

        # Only 2 should be within the last 7 days (from 2026-03-19 and 2026-03-22)
        assert len(snapshots) == 2
        # Should be sorted newest first
        assert snapshots[0].snapshot_id == "snap-recent"
        assert snapshots[1].snapshot_id == "snap-old"

    @patch("polyclaw.dr.recovery.boto3")
    def test_list_available_snapshots_empty(self, mock_boto3):
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"DBSnapshots": []}]
        mock_boto3.client.return_value.get_paginator.return_value = mock_paginator

        manager = DisasterRecoveryManager()
        snapshots = manager.list_available_snapshots(days=7)
        assert snapshots == []

    # -------------------------------------------------------------------------
    # get_latest_snapshot tests
    # -------------------------------------------------------------------------

    @patch("polyclaw.dr.recovery.boto3")
    def test_get_latest_snapshot_found(self, mock_boto3):
        mock_page = {
            "DBSnapshots": [
                {
                    "DBSnapshotIdentifier": "snap-newest",
                    "DBInstanceIdentifier": "polyclaw-db",
                    "SnapshotCreateTime": datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc),
                    "Status": "available",
                    "Encrypted": True,
                    "AllocatedStorage": 20,
                },
            ]
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_page]
        mock_boto3.client.return_value.get_paginator.return_value = mock_paginator

        manager = DisasterRecoveryManager()
        latest = manager.get_latest_snapshot()

        assert latest is not None
        assert latest.snapshot_id == "snap-newest"

    @patch("polyclaw.dr.recovery.boto3")
    def test_get_latest_snapshot_none(self, mock_boto3):
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"DBSnapshots": []}]
        mock_boto3.client.return_value.get_paginator.return_value = mock_paginator

        manager = DisasterRecoveryManager()
        latest = manager.get_latest_snapshot()
        assert latest is None

    # -------------------------------------------------------------------------
    # restore_from_snapshot tests
    # -------------------------------------------------------------------------

    @patch("polyclaw.dr.recovery.boto3")
    def test_restore_from_snapshot_success(self, mock_boto3):
        mock_rds = MagicMock()
        mock_waiter = MagicMock()
        mock_rds.get_waiter.return_value = mock_waiter
        mock_boto3.client.return_value = mock_rds

        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        manager = DisasterRecoveryManager(audit_session_factory=factory)

        report = manager.restore_from_snapshot(
            snapshot_id="snap-test",
            target_db_id="polyclaw-db-restored",
            target_security_groups=["sg-123"],
            wait_for_ready=True,
        )

        assert report.success is True
        assert report.operation == "restore_from_snapshot"
        assert "snap-test" in report.message
        mock_rds.restore_db_instance_from_db_snapshot.assert_called_once()
        mock_waiter.wait.assert_called_once()

    @patch("polyclaw.dr.recovery.boto3")
    def test_restore_from_snapshot_failure(self, mock_boto3):
        mock_rds = MagicMock()
        mock_rds.restore_db_instance_from_db_snapshot.side_effect = Exception("Snapshot not found")
        mock_boto3.client.return_value = mock_rds

        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        manager = DisasterRecoveryManager(audit_session_factory=factory)

        report = manager.restore_from_snapshot(
            snapshot_id="snap-nonexistent",
            target_db_id="polyclaw-db-restored",
        )

        assert report.success is False
        assert "failed" in report.message.lower()

    @patch("polyclaw.dr.recovery.boto3")
    def test_restore_from_snapshot_dry_run(self, mock_boto3):
        """When wait_for_ready=False, no waiter is called."""
        mock_rds = MagicMock()
        mock_boto3.client.return_value = mock_rds

        manager = DisasterRecoveryManager()
        report = manager.restore_from_snapshot(
            snapshot_id="snap-test",
            target_db_id="polyclaw-db-restored",
            wait_for_ready=False,
        )

        assert report.success is True
        mock_rds.restore_db_instance_from_db_snapshot.assert_called_once()
        mock_rds.get_waiter.assert_not_called()

    # -------------------------------------------------------------------------
    # switch_read_replica tests
    # -------------------------------------------------------------------------

    @patch("polyclaw.dr.recovery.boto3")
    def test_switch_read_replica_success(self, mock_boto3):
        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"DBInstanceIdentifier": "polyclaw-db-replica"}]
        }
        mock_waiter = MagicMock()
        mock_rds.get_waiter.return_value = mock_waiter
        mock_boto3.client.return_value = mock_rds

        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        manager = DisasterRecoveryManager(audit_session_factory=factory)

        report = manager.switch_read_replica(
            primary_id="polyclaw-db",
            replica_id="polyclaw-db-replica",
        )

        assert report.success is True
        assert "polyclaw-db-replica" in report.message
        mock_rds.promote_read_replica.assert_called_once()
        mock_waiter.wait.assert_called_once()

    @patch("polyclaw.dr.recovery.boto3")
    def test_switch_read_replica_dry_run(self, mock_boto3):
        mock_rds = MagicMock()
        mock_boto3.client.return_value = mock_rds

        manager = DisasterRecoveryManager()
        report = manager.switch_read_replica(
            primary_id="polyclaw-db",
            replica_id="polyclaw-db-replica",
            promote_replica=False,
        )

        assert report.success is True
        assert "Dry-run" in report.message
        mock_rds.promote_read_replica.assert_not_called()

    @patch("polyclaw.dr.recovery.boto3")
    def test_switch_read_replica_not_found(self, mock_boto3):
        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {"DBInstances": []}
        mock_boto3.client.return_value = mock_rds

        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        manager = DisasterRecoveryManager(audit_session_factory=factory)

        report = manager.switch_read_replica(
            primary_id="polyclaw-db",
            replica_id="nonexistent-replica",
        )

        assert report.success is False
        assert "not found" in report.message.lower()

    # -------------------------------------------------------------------------
    # verify_data_integrity tests
    # -------------------------------------------------------------------------

    def test_verify_data_integrity_all_tables_present(self):
        """Test that integrity check passes when all tables exist."""
        manager = DisasterRecoveryManager()

        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = [
            "markets", "evidences", "decisions", "orders",
            "positions", "audit_logs", "proposal_records",
            "shadow_results", "trading_stage_records", "market_whitelist",
        ]

        mock_session = MagicMock()
        mock_session.bind = MagicMock()

        # Patch sqlalchemy.inspect (imported inside the method)
        with patch("sqlalchemy.inspect") as mock_inspect:
            mock_inspect.return_value = mock_inspector
            # Return specific values for each scalar call:
            # 1. markets count, 2. audit_logs count, 3. recent markets, 4. orphan count
            mock_session.scalar.side_effect = [10, 10, 5, 0]
            result = manager.verify_data_integrity(mock_session)

        assert result is True

    def test_verify_data_integrity_missing_tables(self):
        """Test that integrity check fails when tables are missing."""
        manager = DisasterRecoveryManager()

        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = ["markets", "audit_logs"]

        mock_session = MagicMock()
        mock_session.bind = MagicMock()

        with patch("sqlalchemy.inspect") as mock_inspect:
            mock_inspect.return_value = mock_inspector
            result = manager.verify_data_integrity(mock_session)

        assert result is False

    def test_verify_data_integrity_exception(self):
        """Test that integrity check fails gracefully on exception."""
        manager = DisasterRecoveryManager()

        mock_session = MagicMock()

        with patch("sqlalchemy.inspect") as mock_inspect:
            mock_inspect.side_effect = Exception("Connection lost")
            result = manager.verify_data_integrity(mock_session)

        assert result is False
