"""
Disaster Recovery module for PolyClaw.

Provides tools for orchestrating database failovers, restoring from snapshots,
promoting read replicas, and verifying data integrity after recovery.
"""

from polyclaw.dr.recovery import DisasterRecoveryManager

__all__ = ["DisasterRecoveryManager"]
