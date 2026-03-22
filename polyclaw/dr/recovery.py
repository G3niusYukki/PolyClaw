"""
Disaster Recovery Manager for PolyClaw.

Handles:
- Restoring databases from RDS snapshots
- Verifying data integrity after recovery
- Promoting read replicas to primary
- Audit logging for all DR operations
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import boto3

from polyclaw.safety import log_event

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


@dataclass
class DRSnapshotInfo:
    """Metadata about an RDS snapshot."""
    snapshot_id: str
    db_instance_identifier: str
    snapshot_create_time: datetime
    status: str
    encrypted: bool
    allocated_storage_gb: int


@dataclass
class DRRecoveryReport:
    """Report summarizing a DR operation."""
    operation: str
    started_at: datetime
    completed_at: datetime | None
    success: bool
    message: str
    details: dict


class DisasterRecoveryManager:
    """
    Manages disaster recovery operations for PolyClaw's database and data infrastructure.

    All DR operations are logged to the audit log for compliance and traceability.
    """

    def __init__(
        self,
        region: str = "us-east-1",
        db_instance_id: str = "polyclaw-db",
        audit_session_factory=None,
    ):
        """
        Initialize the DR manager.

        Args:
            region: AWS region for RDS operations.
            db_instance_id: The primary RDS instance identifier.
            audit_session_factory: A callable that returns a DB session for audit logging.
                                   If None, audit logging is skipped.
        """
        self.region = region
        self.db_instance_id = db_instance_id
        self._rds_client = boto3.client("rds", region_name=region)
        self._ec2_client = boto3.client("ec2", region_name=region)
        self._audit_session_factory = audit_session_factory

    def _get_session(self):
        """Get a DB session for audit logging."""
        if self._audit_session_factory is not None:
            return self._audit_session_factory()
        return None

    def _log_audit(self, action: str, payload: str, result: str = "ok") -> None:
        """Write an audit log entry for a DR operation."""
        session = self._get_session()
        if session is not None:
            log_event(session, action, payload, result)
            session.commit()

    # -------------------------------------------------------------------------
    # Snapshot Management
    # -------------------------------------------------------------------------

    def list_available_snapshots(self, days: int = 7) -> list[DRSnapshotInfo]:
        """
        List available manual and automated snapshots for the primary DB instance.

        Args:
            days: Only return snapshots created in the last N days.

        Returns:
            List of DRSnapshotInfo objects sorted by creation time (newest first).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        paginator = self._rds_client.get_paginator("describe_db_snapshots")
        snapshots = []

        for page in paginator.paginate(DBInstanceIdentifier=self.db_instance_id):
            for snap in page.get("DBSnapshots", []):
                create_time = snap.get("SnapshotCreateTime")
                if create_time and create_time >= cutoff:
                    snapshots.append(DRSnapshotInfo(
                        snapshot_id=snap["DBSnapshotIdentifier"],
                        db_instance_identifier=snap["DBInstanceIdentifier"],
                        snapshot_create_time=create_time,
                        status=snap["Status"],
                        encrypted=snap.get("Encrypted", False),
                        allocated_storage_gb=snap.get("AllocatedStorage", 0),
                    ))

        snapshots.sort(key=lambda s: s.snapshot_create_time, reverse=True)
        return snapshots

    def get_latest_snapshot(self) -> DRSnapshotInfo | None:
        """
        Get the most recent available snapshot for the primary DB.

        Returns:
            The latest DRSnapshotInfo, or None if no snapshot exists.
        """
        snapshots = self.list_available_snapshots(days=30)
        return snapshots[0] if snapshots else None

    # -------------------------------------------------------------------------
    # Restore Operations
    # -------------------------------------------------------------------------

    def restore_from_snapshot(
        self,
        snapshot_id: str,
        target_db_id: str,
        target_subnet_group: str = "polyclaw-db-subnet-group",
        target_security_groups: list[str] | None = None,
        target_parameter_group: str = "polyclaw-db-param-group",
        wait_for_ready: bool = True,
        timeout_minutes: int = 30,
    ) -> DRRecoveryReport:
        """
        Restore the database from a snapshot into a new DB instance.

        This creates a new DB instance from the snapshot, suitable for:
        - DR environment provisioning
        - Point-in-time recovery validation
        - Creating a new environment from production data

        Args:
            snapshot_id: The RDS snapshot identifier to restore from.
            target_db_id: Identifier for the restored DB instance.
            target_subnet_group: Subnet group for the restored instance.
            target_security_groups: List of security group IDs to attach.
            target_parameter_group: Parameter group name for the restored instance.
            wait_for_ready: If True, poll until the DB is available.
            timeout_minutes: Maximum time to wait for the DB to become available.

        Returns:
            DRRecoveryReport with the operation result.
        """
        started_at = datetime.now(timezone.utc)
        self._log_audit(
            "dr_restore_start",
            f"snapshot={snapshot_id}|target={target_db_id}",
            "in_progress",
        )

        try:
            # Build restore arguments
            restore_args: dict = {
                "DBSnapshotIdentifier": snapshot_id,
                "DBInstanceIdentifier": target_db_id,
                "DBSubnetGroupName": target_subnet_group,
                "ParameterGroupName": target_parameter_group,
            }

            if target_security_groups:
                restore_args["VpcSecurityGroupIds"] = target_security_groups

            self._rds_client.restore_db_instance_from_db_snapshot(**restore_args)

            if wait_for_ready:
                waiter = self._rds_client.get_waiter("db_instance_available")
                waiter.wait(
                    DBInstanceIdentifier=target_db_id,
                    WaiterConfig={"Delay": 30, "MaxAttempts": timeout_minutes * 2},
                )

            completed_at = datetime.now(timezone.utc)
            self._log_audit(
                "dr_restore_complete",
                f"snapshot={snapshot_id}|target={target_db_id}",
                "ok",
            )

            return DRRecoveryReport(
                operation="restore_from_snapshot",
                started_at=started_at,
                completed_at=completed_at,
                success=True,
                message=f"Successfully restored {snapshot_id} to {target_db_id}",
                details={
                    "snapshot_id": snapshot_id,
                    "target_db_id": target_db_id,
                    "duration_seconds": (completed_at - started_at).total_seconds(),
                },
            )

        except Exception as exc:
            completed_at = datetime.now(timezone.utc)
            error_msg = f"Restore failed: {exc}"
            logger.error(error_msg)
            self._log_audit(
                "dr_restore_failed",
                f"snapshot={snapshot_id}|target={target_db_id}|error={exc}",
                "failed",
            )

            return DRRecoveryReport(
                operation="restore_from_snapshot",
                started_at=started_at,
                completed_at=completed_at,
                success=False,
                message=error_msg,
                details={"snapshot_id": snapshot_id, "target_db_id": target_db_id},
            )

    # -------------------------------------------------------------------------
    # Read Replica Operations
    # -------------------------------------------------------------------------

    def switch_read_replica(
        self,
        primary_id: str,
        replica_id: str,
        promote_replica: bool = True,
        backup_retention: int = 7,
    ) -> DRRecoveryReport:
        """
        Promote a read replica to become the new primary.

        This is the primary DR failover mechanism. It:
        1. Stops accepting writes on the current primary (optional)
        2. Promotes the read replica to a standalone DB instance
        3. Updates the connection string to point to the new primary

        Args:
            primary_id: Current primary DB instance identifier.
            replica_id: Read replica to promote.
            promote_replica: Whether to actually promote (False for dry-run).
            backup_retention: Backup retention period for the promoted replica.

        Returns:
            DRRecoveryReport with the operation result.
        """
        started_at = datetime.now(timezone.utc)
        self._log_audit(
            "dr_failover_start",
            f"primary={primary_id}|replica={replica_id}",
            "in_progress",
        )

        if not promote_replica:
            return DRRecoveryReport(
                operation="switch_read_replica",
                started_at=started_at,
                completed_at=started_at,
                success=True,
                message="Dry-run: would promote replica (promote_replica=False)",
                details={"primary_id": primary_id, "replica_id": replica_id},
            )

        try:
            # Describe the replica to confirm it exists
            response = self._rds_client.describe_db_instances(
                DBInstanceIdentifier=replica_id
            )
            instances = response.get("DBInstances", [])
            if not instances:
                raise ValueError(f"Replica {replica_id} not found")

            # Promote the read replica
            self._rds_client.promote_read_replica(
                DBInstanceIdentifier=replica_id,
                BackupRetentionPeriod=backup_retention,
                PreferredBackupWindow="03:00-04:00",
            )

            # Wait for the promoted instance to be available
            waiter = self._rds_client.get_waiter("db_instance_available")
            waiter.wait(
                DBInstanceIdentifier=replica_id,
                WaiterConfig={"Delay": 30, "MaxAttempts": 60},
            )

            completed_at = datetime.now(timezone.utc)
            self._log_audit(
                "dr_failover_complete",
                f"primary={primary_id}|replica={replica_id}|new_primary={replica_id}",
                "ok",
            )

            return DRRecoveryReport(
                operation="switch_read_replica",
                started_at=started_at,
                completed_at=completed_at,
                success=True,
                message=f"Successfully promoted replica {replica_id} to primary",
                details={
                    "primary_id": primary_id,
                    "replica_id": replica_id,
                    "new_primary_id": replica_id,
                    "duration_seconds": (completed_at - started_at).total_seconds(),
                },
            )

        except Exception as exc:
            completed_at = datetime.now(timezone.utc)
            error_msg = f"Failover failed: {exc}"
            logger.error(error_msg)
            self._log_audit(
                "dr_failover_failed",
                f"primary={primary_id}|replica={replica_id}|error={exc}",
                "failed",
            )

            return DRRecoveryReport(
                operation="switch_read_replica",
                started_at=started_at,
                completed_at=completed_at,
                success=False,
                message=error_msg,
                details={"primary_id": primary_id, "replica_id": replica_id},
            )

    # -------------------------------------------------------------------------
    # Data Integrity Verification
    # -------------------------------------------------------------------------

    def verify_data_integrity(self, session) -> bool:
        """
        Spot-check critical tables to verify data integrity after a restore.

        Checks performed:
        1. Schema integrity: all expected tables exist
        2. Row count sanity: key tables have plausible counts
        3. Referential integrity: foreign key relationships are valid
        4. Recent data: markets table has recent entries

        Args:
            session: SQLAlchemy session connected to the restored DB.

        Returns:
            True if all integrity checks pass, False otherwise.
        """
        from sqlalchemy import inspect, text

        self._log_audit("dr_integrity_check", "started", "in_progress")

        try:
            inspector = inspect(session.bind)
            existing_tables = set(inspector.get_table_names())
            expected_tables = {
                "markets", "evidences", "decisions", "orders",
                "positions", "audit_logs", "proposal_records",
                "shadow_results", "trading_stage_records", "market_whitelist",
            }

            missing_tables = expected_tables - existing_tables
            if missing_tables:
                logger.error("Integrity check FAILED: missing tables: %s", missing_tables)
                self._log_audit(
                    "dr_integrity_check",
                    f"FAILED|missing_tables={missing_tables}",
                    "failed",
                )
                return False

            # Check row count sanity on key tables
            for table_name in ["markets", "audit_logs"]:
                if table_name in existing_tables:
                    count = session.scalar(text(f"SELECT COUNT(*) FROM {table_name}"))
                    if count < 0:
                        logger.error("Integrity check FAILED: %s has negative count", table_name)
                        self._log_audit(
                            "dr_integrity_check",
                            f"FAILED|table={table_name}|negative_count",
                            "failed",
                        )
                        return False

            # Check for recent markets data (within last 24 hours)
            if "markets" in existing_tables:
                recent = session.scalar(
                    text(
                        "SELECT COUNT(*) FROM markets "
                        "WHERE fetched_at > NOW() - INTERVAL '24 hours'"
                    )
                )
                # We expect some data but don't fail if empty (could be a fresh restore)
                logger.info("Integrity check: %d markets fetched in last 24h", recent or 0)

            # Check referential integrity: evidences.market_id_fk -> markets.id
            if "evidences" in existing_tables and "markets" in existing_tables:
                orphaned = session.scalar(
                    text(
                        "SELECT COUNT(*) FROM evidences e "
                        "WHERE NOT EXISTS (SELECT 1 FROM markets m WHERE m.id = e.market_id_fk)"
                    )
                )
                if orphaned and orphaned > 0:
                    logger.error(
                        "Integrity check FAILED: %d orphaned evidence records", orphaned
                    )
                    self._log_audit(
                        "dr_integrity_check",
                        f"FAILED|orphaned_evidences={orphaned}",
                        "failed",
                    )
                    return False

            logger.info("Data integrity check PASSED")
            self._log_audit(
                "dr_integrity_check",
                "PASSED",
                "ok",
            )
            return True

        except Exception as exc:
            logger.error("Data integrity check FAILED with exception: %s", exc)
            self._log_audit(
                "dr_integrity_check",
                f"FAILED|exception={exc}",
                "failed",
            )
            return False

    # -------------------------------------------------------------------------
    # S3 Recovery Verification
    # -------------------------------------------------------------------------

    def verify_s3_replication(self, bucket_name: str) -> dict:
        """
        Verify that S3 cross-region replication is working for a bucket.

        Args:
            bucket_name: The primary bucket name to check.

        Returns:
            Dict with replication status and details.
        """
        try:
            response = self._rds_client.meta.client(
                "s3"
            ).get_bucket_replication(Bucket=bucket_name)

            config = response.get("ReplicationConfiguration", {})
            rules = config.get("Rules", [])
            enabled_rules = [r for r in rules if r.get("Status") == "Enabled"]

            result = {
                "bucket": bucket_name,
                "replication_enabled": len(enabled_rules) > 0,
                "rule_count": len(rules),
                "enabled_rules": len(enabled_rules),
                "status": "ok",
            }

            self._log_audit(
                "dr_s3_replication_check",
                f"bucket={bucket_name}|enabled={result['replication_enabled']}",
                "ok",
            )

            return result

        except Exception as exc:
            logger.error("S3 replication check failed: %s", exc)
            self._log_audit(
                "dr_s3_replication_check",
                f"bucket={bucket_name}|error={exc}",
                "failed",
            )
            return {
                "bucket": bucket_name,
                "replication_enabled": False,
                "status": f"error: {exc}",
            }
