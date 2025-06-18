# ENHANCED QuickBooks Timeout Fix with MIGRATE-ALL Absolute Priority

## 🚀 Problem Solved

This enhanced solution completely eliminates QuickBooks operations getting stuck or hanging indefinitely by implementing:

- **ABSOLUTE PRIORITY for MIGRATE-ALL operations** (NEW)
- **Dynamic background job pausing** during QuickBooks exports
- **Intelligent timeout protection** with progressive escalation
- **Real-time progress tracking** for complete visibility
- **Smart chunked processing** for datasets of any size
- **Enterprise-grade resource management**

## 🎯 NEW: MIGRATE-ALL Absolute Priority System

The **migrate-all** operation now has **ABSOLUTE PRIORITY** over all other background tasks:

### Priority Hierarchy (Highest to Lowest):
1. **🎯 MIGRATE-ALL** - 15 minutes timeout, ALL background jobs paused
2. **🔄 Other QuickBooks** - 10 minutes timeout, background jobs paused  
3. **📊 Export Operations** - 5 minutes timeout
4. **⚙️ Standard Operations** - 2 minutes timeout

### What Happens During MIGRATE-ALL:
- ✅ **ALL scheduler jobs are dynamically paused** (email download, statement download, Google Sheets sync, mapping updates)
- ✅ **Dedicated database connection pool** (15 connections) reserved for migrate-all
- ✅ **15-minute timeout** protection (vs 10 minutes for other QB operations)
- ✅ **Real-time progress tracking** with operation status
- ✅ **Automatic job resumption** when migrate-all completes

## 🛠️ Quick Setup

### Step 1: Configure Environment Variables

**Create or update your `.env` file with these ENHANCED settings:**

```bash
# CRITICAL: Enhanced QuickBooks Timeout Settings
QB_OPERATION_TIMEOUT=600          # 10 minutes for standard QB operations
QB_CHUNK_SIZE=500                 # Process in chunks of 500
QB_CHUNK_DELAY=1.0                # 1 second between chunks
REQUEST_TIMEOUT_QUICKBOOKS=600    # 10 minutes for QB operations
DB_BULK_OPERATION_TIMEOUT=300     # 5 minutes for bulk operations

# NEW: MIGRATE-ALL Absolute Priority Settings
REQUEST_TIMEOUT_MIGRATE_ALL=900   # 15 minutes for MIGRATE-ALL (HIGHEST)
MIGRATE_ALL_ABSOLUTE_PRIORITY=true       # Enable absolute priority
MIGRATE_ALL_PAUSE_ALL_JOBS=true          # Pause ALL background jobs

# Enhanced Priority Control
QB_PRIORITY_MODE=true             # Enable priority mode
QB_PAUSE_BACKGROUND_JOBS=true     # Pause background jobs during QB
QB_DEDICATED_POOL_SIZE=15         # Dedicated connections for QB
```

2. **Or manually add these critical timeout settings to your existing `.env`:**
   ```bash
   # CRITICAL: QuickBooks Timeout Settings
   QB_OPERATION_TIMEOUT=600          # 10 minutes
   QB_CHUNK_SIZE=500                 # Process in chunks of 500
   QB_CHUNK_DELAY=1.0                # 1 second between chunks
   REQUEST_TIMEOUT_QUICKBOOKS=600    # 10 minutes for QB operations
   DB_BULK_OPERATION_TIMEOUT=300     # 5 minutes for bulk operations
   QB_PRIORITY_MODE=true             # Enable priority mode
   QB_PAUSE_BACKGROUND_JOBS=true     # Pause background jobs during QB
   ```

### Step 2: Start the Server with Enhanced Timeout Protection

**Option A: Use the enhanced startup script (RECOMMENDED)**
```bash
python mpi_backend/startup_with_timeouts.py
```

**Option B: Use uvicorn with proper timeout settings**
```bash
uvicorn mpi_backend.main:app --host 0.0.0.0 --port 8080 --timeout-keep-alive 65
```

### Step 3: Monitor Progress (Enhanced Features)

You can now track QuickBooks operation progress in real-time:

```bash
# Check progress of a specific operation
curl http://localhost:8080/quickbooks/progress/{operation_id}
```

The response will show:
```json
{
  "operation_id": "qb_migrate_all_1671234567",
  "stage": "processing_data",
  "progress": 45,
  "message": "Processing 2,500 items",
  "timestamp": 1671234567.89
}
```

**NEW: Check priority system status:**
```bash
curl http://localhost:8080/quickbooks/priority-status
```

Response shows:
```json
{
  "priority_mode_enabled": true,
  "migrate_all_active": false,
  "scheduler_available": true,
  "pauseable_jobs": ["email_download", "statement_download", "google_sheets_sync", "update_all_mappings_daily"]
}
```

## 🔧 Configuration Options

### For Large Datasets (>5000 invoices)
```bash
QB_CHUNK_SIZE=250                 # Smaller chunks
QB_CHUNK_DELAY=2.0                # Longer delays
QB_OPERATION_TIMEOUT=900          # 15 minutes
MIGRATE_ALL_TIMEOUT=1200          # 20 minutes for migrate-all
QB_MAX_CONCURRENT_EXPORTS=1       # One at a time
```

### For Faster Processing (smaller datasets)
```bash
QB_CHUNK_SIZE=1000                # Larger chunks
QB_CHUNK_DELAY=0.5                # Shorter delays
QB_OPERATION_TIMEOUT=300          # 5 minutes
MIGRATE_ALL_TIMEOUT=600           # 10 minutes for migrate-all
QB_MAX_CONCURRENT_EXPORTS=3       # More concurrent
```

### For Maximum Reliability
```bash
QB_CHUNK_SIZE=100                 # Very small chunks
QB_CHUNK_DELAY=3.0                # Longer delays
MIGRATE_ALL_PAUSE_ALL_JOBS=true   # Pause everything during migrate-all
QB_DEDICATED_POOL_SIZE=20         # More dedicated connections
```

## 📊 Performance Improvements

### Before vs After Enhancement:

| Feature | Before | After (Enhanced) |
|---------|--------|------------------|
| Timeout Protection | ❌ None | ✅ Progressive (2-15 min) |
| Background Job Control | ❌ Conflicts | ✅ Dynamic Pausing |
| MIGRATE-ALL Priority | ❌ Same as others | ✅ **ABSOLUTE PRIORITY** |
| Progress Tracking | ❌ None | ✅ Real-time with stages |
| Large Dataset Handling | ❌ Fails/hangs | ✅ Smart chunking |
| Resource Management | ❌ Shared pool | ✅ Dedicated QB pool |
| Error Recovery | ❌ Manual restart | ✅ Auto job resumption |

### NEW: Priority Flow Diagram

```
[MIGRATE-ALL Request] 
        ↓
[Pause ALL Background Jobs]
        ↓
[Reserve 15 DB Connections]
        ↓
[15-minute Timeout Protection]
        ↓
[Process with Absolute Priority]
        ↓
[Resume ALL Background Jobs]
```

## 🧪 Testing

**Run the enhanced test suite:**
```bash
python test_quickbooks_timeout_fix.py
```

**NEW: Tests now include:**
- ✅ MIGRATE-ALL absolute priority system
- ✅ Dynamic scheduler control  
- ✅ Background job coordination
- ✅ Enhanced timeout configurations
- ✅ Progress tracking system
- ✅ Chunked processing logic

## ⚡ Key Features

### 🎯 MIGRATE-ALL Absolute Priority (NEW)
- **Highest timeout**: 15 minutes (vs 10 for other QB operations)
- **ALL background jobs paused**: No interference from any background task
- **Dedicated resources**: 15 database connections reserved
- **Real-time tracking**: Progress updates every stage

### 🔄 Smart Background Job Management
- **Dynamic pausing**: Jobs pause automatically during QB exports
- **Automatic resumption**: Jobs resume when QB operations complete  
- **No conflicts**: Zero interference between operations
- **Scheduler control**: Direct APScheduler job pause/resume

### ⏱️ Progressive Timeout Protection
- **MIGRATE-ALL**: 15 minutes (ABSOLUTE PRIORITY)
- **QuickBooks**: 10 minutes timeout
- **Exports**: 5 minutes timeout
- **Standard**: 2 minutes timeout

### 📈 Real-time Progress Tracking
- **Stage-by-stage updates**: initializing → filtering → processing → uploading → completed
- **Progress percentages**: 0% to 100% with detailed messages
- **Operation IDs**: Track multiple operations simultaneously
- **Timestamp tracking**: Monitor operation duration

### 🔀 Intelligent Chunked Processing
- **Auto-chunking**: Datasets >1000 invoices processed in chunks
- **Configurable size**: Default 500 invoices per chunk
- **Smart delays**: 1-second pause between chunks
- **Memory efficient**: Prevents memory overflow on large datasets

## 🚀 Production Deployment

### Environment Variables Template
```bash
# Copy this to your .env file
QB_OPERATION_TIMEOUT=600
QB_CHUNK_SIZE=500
QB_CHUNK_DELAY=1.0
REQUEST_TIMEOUT_MIGRATE_ALL=900
REQUEST_TIMEOUT_QUICKBOOKS=600
REQUEST_TIMEOUT_EXPORT=300
REQUEST_TIMEOUT_DEFAULT=120
MIGRATE_ALL_ABSOLUTE_PRIORITY=true
MIGRATE_ALL_PAUSE_ALL_JOBS=true
QB_PRIORITY_MODE=true
QB_PAUSE_BACKGROUND_JOBS=true
QB_DEDICATED_POOL_SIZE=15
QB_MAX_CONCURRENT_EXPORTS=3
DB_BULK_OPERATION_TIMEOUT=300
S3_UPLOAD_TIMEOUT=300
```

### Startup Command
```bash
# Enhanced startup with priority control
python mpi_backend/startup_with_timeouts.py

# Or with uvicorn
uvicorn mpi_backend.main:app --host 0.0.0.0 --port 8080 --timeout-keep-alive 65
```

## 🎉 Success Indicators

When working correctly, you should see:

```
🚀 MPI Backend started with ENHANCED timeout protections:
   🎯 MIGRATE-ALL operations: 15 minutes timeout (ABSOLUTE PRIORITY)
   ⏱️  Other QuickBooks operations: 10 minutes timeout
   📊 Export operations: 5 minutes timeout
   🔄 Standard operations: 2 minutes timeout
   🚫 Dynamic job pausing: ACTIVE
   ⚡ Priority control middleware: ACTIVE
```

**During MIGRATE-ALL operation:**
```
🎯 MIGRATE-ALL operation started - ABSOLUTE PRIORITY - timeout: 900s
🚫 ABSOLUTE PRIORITY: Paused scheduler jobs: ['email_download', 'statement_download', 'google_sheets_sync', 'update_all_mappings_daily']
✅ MIGRATE-ALL completed in 245.67s
▶️  PRIORITY RELEASED: Resumed scheduler jobs: ['email_download', 'statement_download', 'google_sheets_sync', 'update_all_mappings_daily']
```

## ❓ Troubleshooting

### MIGRATE-ALL taking too long?
1. **Check dataset size**: `QB_CHUNK_SIZE=250` for very large datasets
2. **Increase timeout**: `MIGRATE_ALL_TIMEOUT=1200` (20 minutes)
3. **Monitor progress**: Use `/quickbooks/progress/{operation_id}`

### Background jobs not resuming?
1. **Check logs**: Look for "PRIORITY RELEASED" messages
2. **Manual resume**: Restart the application if needed
3. **Check configuration**: Ensure `MIGRATE_ALL_PAUSE_ALL_JOBS=true`

### Still getting timeouts?
1. **Verify environment**: Run `python test_quickbooks_timeout_fix.py`
2. **Check middleware**: Ensure timeout middleware is active
3. **Database connections**: Increase `QB_DEDICATED_POOL_SIZE=20`

---

## 🎯 Summary

This enhanced solution provides **ABSOLUTE PRIORITY** for MIGRATE-ALL operations with:
- ✅ **15-minute timeout protection** (highest priority)
- ✅ **ALL background jobs paused** during migrate-all
- ✅ **Dynamic scheduler control** with automatic job management
- ✅ **Real-time progress tracking** with detailed stages
- ✅ **Smart chunked processing** for any dataset size
- ✅ **Enterprise-grade resource management**

**Result**: QuickBooks operations will never get stuck again, and MIGRATE-ALL has absolute priority over all other system operations. 