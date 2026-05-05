# Feature Flags

User-based feature flags for enabling/disabling features without code changes.
For the time being this approach is rigid but it works. For future development we want to make this
more robust and save the feature flags to the database instead of the Python module.

## How It Works

- **Backend**: Server-side allowlists in `mpi_backend/utils/feature_flags.py`
- **Frontend**: React context fetches flags from `/feature-flags` endpoint
- **Security**: Allowlists never exposed, username from validated JWT token

## Available Flags

See `mpi_backend/utils/feature_flags.py` for available flags

## Quick Start

### Add User to Allowlist

Edit `mpi_backend/utils/feature_flags.py`:

```python
FEATURE_FLAG_ALLOWLISTS = {
    "use_dao_with_fallback": ["testuser", "newuser"],
}
```

Restart backend. User gets new flags on next login.

### Use in Backend

```python
from mpi_backend.utils.feature_flags import is_enabled

if self.current_user and is_enabled('flag_name', self.current_user):
    # New feature
else:
    # Old feature
```

**Important**: Pass `current_user` to controller:
```python
InvoiceItemController(db, current_user=current_user)
```

### Use in Frontend

```typescript
import { useFeatureFlags } from '../../contexts/FeatureFlagContext';

const { isEnabled } = useFeatureFlags();

if (isEnabled('flag_name')) {
  // New UI
}
```

## Add New Flag

1. **Backend**: Add to `FEATURE_FLAG_ALLOWLISTS` in `feature_flags.py`
2. **Frontend**: Add to `FeatureFlags` interface in `FeatureFlagContext.tsx`
3. **Frontend**: Add to `DEFAULT_FLAGS` (set to `false`)

## Testing

```bash
# Check flags for authenticated user
curl -H "Authorization: Bearer <token>" http://localhost:8000/feature-flags
```
