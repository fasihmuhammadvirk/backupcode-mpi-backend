# QuickBooks Business Logic Update

## Overview
This document describes the major update to the QuickBooks export business logic in `mpi_backend/api/routes/quickbooks.py`. The update implements a new tax distribution system and class-based splitting that creates multiple lines per invoice based on equipment/materials and class values.

## Key Changes

### 1. Tax Distribution Logic
**Previous Logic**: Tax was added once per invoice as a single line
**New Logic**: Tax is distributed proportionally to each item based on the tax percentage

#### Tax Calculation Formula
```
Tax Percentage = (Tax Amount / Item Total) × 100
Item Amount with Tax = Item Amount × (1 + Tax Percentage / 100)
```

#### Example
- Invoice total: $1000 (items: $900, tax: $100)
- Tax percentage: (100/900) × 100 = 11.1111%
- Item E1 ($100): $100 × (1 + 11.1111/100) = $111.11
- Item E2 ($200): $200 × (1 + 11.1111/100) = $222.22
- Item M1 ($600): $600 × (1 + 11.1111/100) = $666.67

### 2. Class-Based Account Mapping
**Priority Order**:
1. **Class-based mapping** (highest priority)
   - Class 'A' → `UnInvoiced JIP:Material:Additional Material`
   - Class 'L' → `UnInvoiced JIP:Subcontractors Expense:Labor`

2. **Sheet name classification** (fallback)
   - Uses existing item classification system
   - Materials (M) → `UnInvoiced JIP:Cost Of Materials:Job Materials Purchased`
   - Equipment (E) → `UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased`

3. **Special case mappings** (safety net)
   - UIDI-Job Materials Purchased → `UnInvoiced JIP:Cost Of Materials:Job Materials Purchased`
   - UIDI-Job Equipment → `UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased`
   - UIDI-Sprinkler specialty item → `UnInvoiced JIP:Cost Of Materials:Job Materials Purchased`
   - UIDI-Drainage Material → `UnInvoiced JIP:Cost Of Materials:Job Materials Purchased`

4. **Default mapping**
   - Unmatched items → `UnInvoiced JIP:Cost Of Materials:Job Materials Purchased`

### 3. Batch Entry Structure
**Previous Structure**: One line per invoice
**New Structure**: Multiple lines per invoice

#### Line Types per Invoice:
1. **Equipment/Materials lines**: One line per account-class combination
   - Materials with Class A
   - Equipment with Class L  
   - Materials without class
   - Equipment without class

2. **Total line**: Final line showing total invoice amount including tax

#### Example Output Structure:
```
Line 1: Materials (Class A) - $111.11
Line 2: Equipment (Class L) - $222.22  
Line 3: Materials (No Class) - $666.67
Line 4: TOTAL INVOICE AMOUNT - $1000.00
```

## Implementation Details

### Code Changes
1. **Tax Percentage Calculation**: Added logic to calculate tax percentage per invoice
2. **Proportional Tax Distribution**: Each item gets tax added proportionally
3. **Account Classification**: Enhanced classification logic with priority order
4. **Batch Entry Generation**: Complete rewrite of aggregation logic to create multiple lines
5. **Validation**: Maintained existing validation for "No Match" items and unmatched sheet names

### Key Functions Modified
- `migrate_invoice_to_QB_ultra_fast()`: Main function with new business logic
- Tax calculation and distribution logic
- Account classification with priority system
- Batch entry generation with class-based splitting

### Data Flow
1. **Input**: Invoice items with amounts, classes, and tax information
2. **Processing**: 
   - Calculate tax percentages
   - Distribute tax proportionally to items
   - Classify items by account based on priority rules
   - Group items by account-class combinations
3. **Output**: Multiple batch entry lines per invoice with tax-inclusive amounts

## Benefits

### 1. Accurate Tax Distribution
- Tax is now distributed proportionally to each item
- Eliminates tax allocation issues in QuickBooks
- Provides more accurate cost tracking

### 2. Class-Based Splitting
- Items are properly categorized by class values
- Equipment and materials are separated correctly
- Maintains class information in QuickBooks

### 3. Detailed Reporting
- Multiple lines provide better granularity
- Easier to track costs by category and class
- Better integration with QuickBooks reporting

### 4. Backward Compatibility
- Maintains existing validation logic
- Preserves error handling for unmapped items
- Keeps existing status update functionality

## Testing

The new logic has been tested with the example scenario:
- **Input**: 3 items ($100, $200, $600) + $100 tax
- **Expected**: 4 lines with proper tax distribution
- **Result**: ✅ All amounts match expected values exactly

## Migration Notes

### For Existing Users
- No changes required to existing data
- New logic applies automatically to all exports
- Existing item classifications continue to work

### For Administrators
- Monitor the new multi-line structure in QuickBooks
- Verify tax distribution accuracy
- Check that class-based splitting works as expected

## Future Enhancements

1. **Additional Class Types**: Support for more class values beyond A and L
2. **Custom Tax Rates**: Per-item or per-category tax rates
3. **Advanced Grouping**: More sophisticated grouping rules
4. **Audit Trail**: Enhanced logging for tax distribution calculations

## Files Modified

- `mpi_backend/api/routes/quickbooks.py`: Main business logic implementation
- Line length fixes applied to comply with PEP 8 standards

## Validation

The implementation includes comprehensive validation:
- ✅ Tax calculation accuracy
- ✅ Account classification priority
- ✅ Class-based splitting
- ✅ Total amount verification
- ✅ Error handling for edge cases 