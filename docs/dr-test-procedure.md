# Disaster Recovery Test Procedure

This document outlines the procedures for testing PolyClaw's disaster recovery capabilities. These tests should be run quarterly or after any infrastructure change.

## RTO/RPO Targets

| Metric | Target | Description |
|--------|--------|-------------|
| RTO (Recovery Time Objective) | < 30 minutes | Time from disaster declaration to service restoration |
| RPO (Recovery Point Objective) | < 1 hour | Maximum acceptable data loss (backed by 7-day RDS retention) |

## Prerequisites

- AWS CLI configured with appropriate credentials
- Access to the production/staging AWS environment
- `polyclaw` CLI installed
- Access to the ECS cluster and RDS instance
- Alert notifications configured (SNS topic: `polyclaw-dr-alerts`)

---

## Test 1: RDS Failover Test (Read Replica Promotion)

### Objective
Verify that the read replica can be promoted to primary and the application reconnects.

### Procedure

```bash
# 1. Identify the primary DB and its read replica
aws rds describe-db-instances \
  --filters "Name=db-instance-id,Values=polyclaw-db" \
  --query 'DBInstances[0].DBInstanceArn'

aws rds describe-db-instances \
  --filters "Name=db-instance-id,Values=polyclaw-db-replica" \
  --query 'DBInstances[0].DBInstanceStatus'

# 2. Verify the replica is "available"
# Expected status: "available"

# 3. Check current primary endpoint
aws rds describe-db-instances \
  --db-instance-identifier polyclaw-db \
  --query 'DBInstances[0].Endpoint.Address'

# 4. Promote the read replica (DR simulation)
aws rds promote-read-replica \
  --db-instance-identifier polyclaw-db-replica \
  --backup-retention-period 7 \
  --preferred-backup-window "03:00-04:00"

# 5. Wait for promotion to complete (5-10 minutes)
aws rds wait db-instance-available \
  --db-instance-identifier polyclaw-db-replica

# 6. Verify the replica is now "available" as a standalone instance
aws rds describe-db-instances \
  --db-instance-identifier polyclaw-db-replica \
  --query 'DBInstances[0].DBInstanceStatus'

# 7. Update connection string in Secrets Manager to point to new primary
aws secretsmanager put-secret-value \
  --secret-id prod/polyclaw/database-url \
  --secret-string "postgresql://user:pass@polyclaw-db-replica.us-east-1.rds.amazonaws.com:5432/polyclaw"

# 8. Restart ECS tasks to pick up new connection
aws ecs update-service \
  --cluster prod-polyclaw-cluster \
  --service prod-polyclaw-api \
  --force-new-deployment

# 9. Verify API is healthy
curl -f https://api.pncl.ai/health

# 10. Verify data integrity
python3 -c "
from polyclaw.dr.recovery import DisasterRecoveryManager
from polyclaw.db import SessionLocal

manager = DisasterRecoveryManager()
session = SessionLocal()
ok = manager.verify_data_integrity(session)
print('Data integrity:', 'PASS' if ok else 'FAIL')
session.close()
"

# 11. Demote back (restore original state) - in a real DR this step is skipped
# The replica stays as the new primary. Recreate a new replica from the promoted instance.
aws rds create-db-instance-read-replica \
  --db-instance-identifier polyclaw-db \
  --source-db-instance-identifier polyclaw-db-replica
```

### Success Criteria
- [ ] Read replica promoted to standalone instance
- [ ] ECS tasks restarted with new connection string
- [ ] API health check returns `200 OK`
- [ ] Data integrity check passes
- [ ] All existing orders and decisions are present

### Rollback
If the promotion causes issues, restore from the most recent snapshot:
```bash
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier polyclaw-db-failback \
  --snapshot-identifier polyclaw-db-$(date +%Y%m%d)
```

---

## Test 2: S3 Restore Test

### Objective
Verify that cross-region replicated data is recoverable from the DR region.

### Procedure

```bash
# 1. Verify replication is configured on primary bucket
aws s3api get-bucket-replication \
  --bucket polyclaw-data-prod

# Expected: ReplicationConfiguration with rules where Status="Enabled"

# 2. Check replication status in DR region
aws s3api get-bucket-replication \
  --bucket polyclaw-data-prod-dr \
  --region us-west-2

# 3. Verify object count in both regions is similar
PRIMARY_COUNT=$(aws s3 ls s3://polyclaw-data-prod --recursive | wc -l)
DR_COUNT=$(aws s3 ls s3://polyclaw-data-prod-dr --recursive --region us-west-2 | wc -l)
echo "Primary objects: $PRIMARY_COUNT, DR objects: $DR_COUNT"

# 4. Download a sample object from DR region to verify accessibility
aws s3 cp s3://polyclaw-data-prod-dr/ \
  /tmp/dr-test/ \
  --recursive \
  --region us-west-2

# 5. Verify encrypted objects
aws s3api get-object-encryption \
  --bucket polyclaw-data-prod-dr \
  --key "path/to/sample/object" \
  --region us-west-2

# 6. Verify versioning is enabled (enables point-in-time recovery)
aws s3api get-bucket-versioning \
  --bucket polyclaw-data-prod-dr \
  --region us-west-2

# 7. Test lifecycle policy
aws s3api get-bucket-lifecycle-configuration \
  --bucket polyclaw-data-prod-dr \
  --region us-west-2
```

### Success Criteria
- [ ] Replication configuration is active with enabled rules
- [ ] Object counts in primary and DR regions are within acceptable delta (< 1%)
- [ ] DR region bucket has versioning enabled
- [ ] DR region bucket has lifecycle policy (transition to Glacier after 1 year)
- [ ] Sample objects can be downloaded from DR region
- [ ] Objects are encrypted with customer-managed KMS key

---

## Test 3: ECS Recovery Test

### Objective
Verify that ECS automatically restarts failed tasks and maintains desired count.

### Procedure

```bash
# 1. Record current task count
DESIRED=$(aws ecs describe-services \
  --cluster prod-polyclaw-cluster \
  --services prod-polyclaw-api \
  --query 'services[0].desiredCount')

echo "Desired task count: $DESIRED"

# 2. Force-stop a running task to simulate a failure
TASK_ARN=$(aws ecs list-tasks \
  --cluster prod-polyclaw-cluster \
  --service-name prod-polyclaw-api \
  --query 'taskArns[0]' \
  --output text)

aws ecs stop-task \
  --cluster prod-polyclaw-cluster \
  --task $TASK_ARN \
  --reason "DR test: forced stop"

# 3. Monitor task replacement (should restart within 2 minutes)
watch -n 10 'aws ecs describe-services \
  --cluster prod-polyclaw-cluster \
  --services prod-polyclaw-api \
  --query "services[0].{Running:runningCount,Pending:pendingCount,Desired:desiredCount}"'

# 4. Verify service is stable
aws ecs wait services-stable \
  --cluster prod-polyclaw-cluster \
  --services prod-polyclaw-api

# 5. Verify API is still healthy
curl -f https://api.pncl.ai/health

# 6. Check CloudWatch logs for task restart
aws logs describe-log-groups \
  --log-group-name-prefix "/ecs/prod/polyclaw"

aws logs tail /ecs/prod/polyclaw/api \
  --since 10m \
  --filter-pattern "START"
```

### Success Criteria
- [ ] ECS automatically starts a replacement task within 2 minutes
- [ ] Service returns to `desiredCount` running tasks
- [ ] API health check returns `200 OK` throughout the test
- [ ] No API errors in CloudWatch logs during restart
- [ ] Service stability is reached within 5 minutes

---

## Test 4: Kill Switch Test

### Objective
Verify that the kill switch immediately halts all trading activity.

### Procedure

```bash
# 1. Check current kill switch status
curl -s https://api.pncl.ai/kill-switch | jq .

# 2. Enable kill switch
curl -X POST "https://api.pncl.ai/kill-switch/enable?reason=DR%20test" | jq .

# 3. Verify kill switch is enabled
curl -s https://api.pncl.ai/kill-switch | jq .

# 4. Attempt to execute a decision (should be blocked)
curl -X POST https://api.pncl.ai/execute-ready | jq .

# 5. Check audit logs for kill switch event
# Verify the kill_switch action was recorded
python3 -c "
from polyclaw.db import SessionLocal
from sqlalchemy import select, desc
from polyclaw.models import AuditLog

session = SessionLocal()
last_kill = session.scalars(
    select(AuditLog).where(AuditLog.action == 'kill_switch').order_by(desc(AuditLog.created_at)).limit(1)
).first()
print(f'Kill switch record: action={last_kill.action}, result={last_kill.result}, payload={last_kill.payload}')
session.close()
"

# 6. Disable kill switch
curl -X POST "https://api.pncl.ai/kill-switch/disable?reason=DR%20test%20complete" | jq .

# 7. Verify execution resumes
curl -X POST https://api.pncl.ai/execute-ready | jq .
```

### Success Criteria
- [ ] Kill switch enables successfully
- [ ] `GET /kill-switch` returns `{"enabled": true, "reason": "DR test"}`
- [ ] Execution endpoint returns appropriate response when kill switch is active
- [ ] Audit log contains kill_switch event with correct reason
- [ ] Kill switch can be disabled
- [ ] Execution resumes after disabling kill switch

---

## Test 5: Database Restore from Snapshot Test

### Objective
Verify that the database can be restored from the latest snapshot into a new instance.

### Procedure

```bash
# 1. Identify the latest snapshot
SNAPSHOT_ID=$(aws rds describe-db-snapshots \
  --db-instance-identifier polyclaw-db \
  --query 'DBSnapshots | sort_by(@, &SnapshotCreateTime) | [-1].DBSnapshotIdentifier' \
  --output text)

echo "Using snapshot: $SNAPSHOT_ID"

# 2. Restore to a new instance (DR environment simulation)
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier polyclaw-db-dr-test \
  --snapshot-identifier $SNAPSHOT_ID \
  --db-subnet-group-name polyclaw-db-subnet-group \
  --no-multi-az

# 3. Wait for restore to complete (10-20 minutes)
aws rds wait db-instance-available \
  --db-instance-identifier polyclaw-db-dr-test

# 4. Verify the restored instance
aws rds describe-db-instances \
  --db-instance-identifier polyclaw-db-dr-test \
  --query 'DBInstances[0].{Status:DBInstanceStatus,Version:EngineVersion}'

# 5. Connect and verify data integrity
RESTORED_ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier polyclaw-db-dr-test \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text)

python3 -c "
from sqlalchemy import create_engine, text
engine = create_engine('postgresql://user:pass@${RESTORED_ENDPOINT}:5432/polyclaw')
with engine.connect() as conn:
    markets_count = conn.execute(text('SELECT COUNT(*) FROM markets')).scalar()
    decisions_count = conn.execute(text('SELECT COUNT(*) FROM decisions')).scalar()
    print(f'Markets: {markets_count}, Decisions: {decisions_count}')
"

# 6. Use the DR manager for integrity check
python3 -c "
from polyclaw.dr.recovery import DisasterRecoveryManager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine('postgresql://user:pass@${RESTORED_ENDPOINT}:5432/polyclaw')
Session = sessionmaker(bind=engine)
session = Session()

manager = DisasterRecoveryManager()
ok = manager.verify_data_integrity(session)
print('Integrity check:', 'PASS' if ok else 'FAIL')
session.close()
"

# 7. Clean up: delete the test instance
aws rds delete-db-instance \
  --db-instance-identifier polyclaw-db-dr-test \
  --skip-final-snapshot
```

### Success Criteria
- [ ] Latest snapshot identified
- [ ] DB instance restored from snapshot successfully
- [ ] Restored instance reaches "available" status
- [ ] Data integrity check passes (all tables present, referential integrity intact)
- [ ] Snapshot is less than 1 hour old (within RPO)
- [ ] Restored instance is in the correct VPC and subnet group

---

## Recovery Checklist (Real DR Event)

When an actual disaster occurs, follow this checklist:

1. **Declare DR** - Notify team via Slack/email
2. **Assess impact** - Determine scope (partial vs full outage)
3. **Activate kill switch** - `POST /kill-switch/enable?reason=DR`
4. **Promote read replica** - Run Test 1 procedure
5. **Update connection strings** - Point to new primary
6. **Restart ECS services** - Force new deployment
7. **Verify API health** - `GET /health`
8. **Verify data integrity** - Run `verify_data_integrity()`
9. **Check S3 replication** - Confirm DR bucket has current data
10. **Monitor alerts** - Watch CloudWatch/SNS for 30 minutes
11. **Disable kill switch** - After verifying service stability
12. **Document incident** - Record timeline, actions taken, lessons learned

---

## Notification Contacts

| Role | Contact |
|------|---------|
| On-call engineer | PagerDuty |
| Infrastructure lead | [email] |
| CTO | [email] |

## Related Documents

- `infrastructure/dr.tf` - Terraform DR resources
- `infrastructure/rds.tf` - RDS configuration (backup retention)
- `infrastructure/s3.tf` - S3 replication configuration
- `polyclaw/dr/recovery.py` - DR Python module
- `SAFETY_CHECKLIST.md` - Pre-live safety checks
