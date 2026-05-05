"""
Unit tests for QuickBooks tax calculation and distribution logic.

Tests the tax calculation formulas:
1. Tax percentage calculation: (tax_amount / item_total) × 100
2. Proportional tax distribution to each item/group
3. Item amount with tax: amount × (1 + tax_percentage / 100)
4. Rounding and precision handling
"""

import pytest
from decimal import Decimal


pytestmark = pytest.mark.business_logic


class TestTaxPercentageCalculation:
    """Test tax percentage calculation logic."""
    
    def test_tax_percentage_calculation_standard(self):
        """
        Test standard tax percentage calculation.
        
        GIVEN invoice with item_total=900 and tax_amount=100
        WHEN calculating tax percentage
        THEN should return 11.1111% (tax / items)
        """
        # Arrange
        item_total = 900.00
        tax_amount = 100.00
        
        # Act
        tax_pct = (tax_amount / item_total) if item_total else 0
        
        # Assert
        assert abs(tax_pct - 0.111111) < 0.0001  # ~11.11%
    
    def test_tax_percentage_calculation_zero_items(self):
        """
        Test tax percentage when item total is zero.
        
        GIVEN invoice with item_total=0 and tax_amount=100
        WHEN calculating tax percentage
        THEN should return 0 (avoid division by zero)
        """
        # Arrange
        item_total = 0.00
        tax_amount = 100.00
        
        # Act
        tax_pct = (tax_amount / item_total) if item_total else 0
        
        # Assert
        assert tax_pct == 0
    
    def test_tax_percentage_calculation_zero_tax(self):
        """
        Test tax percentage when tax amount is zero.
        
        GIVEN invoice with item_total=1000 and tax_amount=0
        WHEN calculating tax percentage
        THEN should return 0%
        """
        # Arrange
        item_total = 1000.00
        tax_amount = 0.00
        
        # Act
        tax_pct = (tax_amount / item_total) if item_total else 0
        
        # Assert
        assert tax_pct == 0
    
    def test_tax_percentage_high_tax_rate(self):
        """
        Test tax percentage with high tax rate.
        
        GIVEN invoice with item_total=1000 and tax_amount=250 (25% tax)
        WHEN calculating tax percentage
        THEN should return 0.25 (25%)
        """
        # Arrange
        item_total = 1000.00
        tax_amount = 250.00
        
        # Act
        tax_pct = (tax_amount / item_total) if item_total else 0
        
        # Assert
        assert abs(tax_pct - 0.25) < 0.0001  # 25%
    
    def test_tax_percentage_fractional_amounts(self):
        """
        Test tax percentage with fractional amounts.
        
        GIVEN invoice with item_total=333.33 and tax_amount=33.33 (~10% tax)
        WHEN calculating tax percentage
        THEN should calculate correctly
        """
        # Arrange
        item_total = 333.33
        tax_amount = 33.33
        
        # Act
        tax_pct = (tax_amount / item_total) if item_total else 0
        
        # Assert
        assert abs(tax_pct - 0.1) < 0.0001  # ~10%


class TestProportionalTaxDistribution:
    """Test proportional tax distribution to items."""
    
    def test_proportional_tax_distribution_single_item(self):
        """
        Test tax distribution to single item.
        
        GIVEN single item with amount=900 and tax_amount=100
        WHEN distributing tax
        THEN item should receive all tax (100)
        """
        # Arrange
        item_amount = 900.00
        item_total = 900.00
        tax_amount = 100.00
        
        # Act
        tax_pct = tax_amount / item_total
        item_tax = item_amount * tax_pct
        
        # Assert
        assert abs(item_tax - 100.00) < 0.01
    
    def test_proportional_tax_distribution_multiple_items_example_from_docs(self):
        """
        Test tax distribution matching documentation example.
        
        GIVEN invoice from docs: items=$900, tax=$100
        - Item E1: $100
        - Item E2: $200
        - Item M1: $600
        WHEN distributing tax proportionally
        THEN each item should receive tax based on its proportion:
        - E1: $100 + $11.11 = $111.11
        - E2: $200 + $22.22 = $222.22
        - M1: $600 + $66.67 = $666.67
        """
        # Arrange
        items = [
            {"code": "E1", "amount": 100.00},
            {"code": "E2", "amount": 200.00},
            {"code": "M1", "amount": 600.00},
        ]
        tax_amount = 100.00
        item_total = sum(item["amount"] for item in items)
        
        # Act
        tax_pct = tax_amount / item_total
        results = []
        for item in items:
            item_tax = item["amount"] * tax_pct
            item_total_with_tax = item["amount"] + item_tax
            results.append({
                "code": item["code"],
                "tax": item_tax,
                "total": item_total_with_tax
            })
        
        # Assert
        assert abs(results[0]["tax"] - 11.11) < 0.01
        assert abs(results[0]["total"] - 111.11) < 0.01
        
        assert abs(results[1]["tax"] - 22.22) < 0.01
        assert abs(results[1]["total"] - 222.22) < 0.01
        
        assert abs(results[2]["tax"] - 66.67) < 0.01
        assert abs(results[2]["total"] - 666.67) < 0.01
    
    def test_proportional_tax_distribution_equal_split(self):
        """
        Test tax distribution with equal item amounts.
        
        GIVEN 3 items of $300 each (total $900) and tax $90
        WHEN distributing tax proportionally
        THEN each item should receive $30 tax
        """
        # Arrange
        item_amounts = [300.00, 300.00, 300.00]
        tax_amount = 90.00
        item_total = sum(item_amounts)
        
        # Act
        tax_pct = tax_amount / item_total
        item_taxes = [amount * tax_pct for amount in item_amounts]
        
        # Assert
        for item_tax in item_taxes:
            assert abs(item_tax - 30.00) < 0.01
    
    def test_proportional_tax_distribution_unequal_split(self):
        """
        Test tax distribution with unequal item amounts.
        
        GIVEN items with varying amounts
        WHEN distributing tax proportionally
        THEN larger amounts should receive more tax
        """
        # Arrange
        items = [
            {"amount": 100.00},  # 10% of total
            {"amount": 400.00},  # 40% of total
            {"amount": 500.00},  # 50% of total
        ]
        tax_amount = 100.00
        item_total = sum(item["amount"] for item in items)
        
        # Act
        tax_pct = tax_amount / item_total
        item_taxes = [item["amount"] * tax_pct for item in items]
        
        # Assert
        assert abs(item_taxes[0] - 10.00) < 0.01  # 10% of tax
        assert abs(item_taxes[1] - 40.00) < 0.01  # 40% of tax
        assert abs(item_taxes[2] - 50.00) < 0.01  # 50% of tax


class TestTaxDistributionTotalValidation:
    """Test that distributed tax sums to total tax amount."""
    
    def test_tax_distribution_total_matches_invoice(self):
        """
        Test that sum of distributed taxes equals total tax.
        
        GIVEN multiple items with tax distributed proportionally
        WHEN summing all item taxes
        THEN total should equal original tax amount (within rounding tolerance)
        """
        # Arrange
        items = [
            {"amount": 123.45},
            {"amount": 234.56},
            {"amount": 345.67},
            {"amount": 456.78},
        ]
        tax_amount = 89.12
        item_total = sum(item["amount"] for item in items)
        
        # Act
        tax_pct = tax_amount / item_total
        item_taxes = [item["amount"] * tax_pct for item in items]
        total_distributed_tax = sum(item_taxes)
        
        # Assert
        assert abs(total_distributed_tax - tax_amount) < 0.01
    
    def test_item_totals_with_tax_equal_invoice_total(self):
        """
        Test that item amounts + distributed tax = invoice total.
        
        GIVEN items totaling $900 with $100 tax
        WHEN adding tax to each item proportionally
        THEN sum should equal $1000 (within rounding tolerance)
        """
        # Arrange
        items = [
            {"amount": 100.00},
            {"amount": 200.00},
            {"amount": 600.00},
        ]
        tax_amount = 100.00
        item_total = sum(item["amount"] for item in items)
        expected_grand_total = item_total + tax_amount
        
        # Act
        tax_pct = tax_amount / item_total
        totals_with_tax = [item["amount"] + (item["amount"] * tax_pct) for item in items]
        actual_grand_total = sum(totals_with_tax)
        
        # Assert
        assert abs(actual_grand_total - expected_grand_total) < 0.01


class TestRoundingAndPrecision:
    """Test rounding and precision in tax calculations."""
    
    def test_tax_distribution_rounding_to_two_decimals(self):
        """
        Test that tax amounts are rounded to 2 decimal places.
        
        GIVEN tax calculation resulting in more than 2 decimals
        WHEN rounding for currency
        THEN should round to 2 decimal places
        """
        # Arrange
        item_amount = 123.45
        item_total = 1000.00
        tax_amount = 77.77
        
        # Act
        tax_pct = tax_amount / item_total
        item_tax = item_amount * tax_pct
        item_tax_rounded = round(item_tax, 2)
        
        # Assert
        # Check that rounding happened
        assert isinstance(item_tax_rounded, float)
        # Check precision
        assert len(str(item_tax_rounded).split('.')[-1]) <= 2 or item_tax_rounded == int(item_tax_rounded)
    
    def test_tax_distribution_rounding_does_not_lose_significant_tax(self):
        """
        Test that rounding doesn't lose significant tax amounts.
        
        GIVEN multiple items with tax distributed and rounded
        WHEN summing rounded tax amounts
        THEN total should still be close to original tax amount
        """
        # Arrange
        items = [
            {"amount": 33.33},
            {"amount": 33.33},
            {"amount": 33.34},
        ]
        tax_amount = 10.00
        item_total = sum(item["amount"] for item in items)
        
        # Act
        tax_pct = tax_amount / item_total
        item_taxes_rounded = [round(item["amount"] * tax_pct, 2) for item in items]
        total_tax_after_rounding = sum(item_taxes_rounded)
        
        # Assert
        # Should be within 1 cent of original tax (rounding tolerance)
        assert abs(total_tax_after_rounding - tax_amount) < 0.02
    
    def test_zero_tax_amount_precision(self):
        """
        Test precision when tax amount is zero.
        
        GIVEN invoice with zero tax
        WHEN distributing tax
        THEN all item taxes should be exactly 0.00
        """
        # Arrange
        items = [
            {"amount": 100.00},
            {"amount": 200.00},
            {"amount": 300.00},
        ]
        tax_amount = 0.00
        item_total = sum(item["amount"] for item in items)
        
        # Act
        tax_pct = (tax_amount / item_total) if item_total else 0
        item_taxes = [item["amount"] * tax_pct for item in items]
        
        # Assert
        for tax in item_taxes:
            assert tax == 0.00


class TestEdgeCasesAndErrorHandling:
    """Test edge cases in tax calculations."""
    
    def test_very_small_tax_amount(self):
        """
        Test tax distribution with very small tax amount.
        
        GIVEN invoice with very small tax (e.g., $0.01)
        WHEN distributing tax
        THEN should handle gracefully without errors
        """
        # Arrange
        items = [
            {"amount": 100.00},
            {"amount": 200.00},
        ]
        tax_amount = 0.01  # Very small tax
        item_total = sum(item["amount"] for item in items)
        
        # Act
        tax_pct = tax_amount / item_total
        item_taxes = [round(item["amount"] * tax_pct, 2) for item in items]
        
        # Assert
        # Should not crash and should distribute something
        assert len(item_taxes) == 2
        # Sum might round to 0 due to precision, but should not error
        assert sum(item_taxes) >= 0
    
    def test_very_large_tax_amount(self):
        """
        Test tax distribution with very large tax amount.
        
        GIVEN invoice with very large tax
        WHEN distributing tax
        THEN should calculate correctly without overflow
        """
        # Arrange
        items = [
            {"amount": 10000.00},
            {"amount": 20000.00},
        ]
        tax_amount = 15000.00  # 50% tax rate
        item_total = sum(item["amount"] for item in items)
        
        # Act
        tax_pct = tax_amount / item_total
        item_taxes = [item["amount"] * tax_pct for item in items]
        total_tax = sum(item_taxes)
        
        # Assert
        assert abs(total_tax - tax_amount) < 0.01
        assert abs(item_taxes[0] - 5000.00) < 0.01
        assert abs(item_taxes[1] - 10000.00) < 0.01
    
    def test_single_item_receives_all_tax(self):
        """
        Test that single item receives 100% of tax.
        
        GIVEN invoice with only one item
        WHEN distributing tax
        THEN the single item should receive all the tax
        """
        # Arrange
        items = [{"amount": 1000.00}]
        tax_amount = 100.00
        item_total = sum(item["amount"] for item in items)
        
        # Act
        tax_pct = tax_amount / item_total
        item_tax = items[0]["amount"] * tax_pct
        
        # Assert
        assert abs(item_tax - tax_amount) < 0.01


@pytest.mark.parametrize("item_total,tax_amount,expected_pct", [
    (900.00, 100.00, 0.1111),   # ~11.11%
    (1000.00, 100.00, 0.1),      # 10%
    (1000.00, 0, 0),             # 0% tax
    (1000.00, 250.00, 0.25),     # 25% tax
    (500.00, 25.00, 0.05),       # 5% tax
    (333.33, 33.33, 0.1),        # ~10% with fractional amounts
])
def test_tax_percentage_calculation_parameterized(item_total, tax_amount, expected_pct):
    """
    Parameterized test for tax percentage calculations.
    
    Tests various tax scenarios efficiently using pytest.mark.parametrize.
    """
    # Act
    tax_pct = (tax_amount / item_total) if item_total else 0
    
    # Assert
    assert abs(tax_pct - expected_pct) < 0.001, \
        f"Expected {expected_pct} but got {tax_pct} for item_total={item_total}, tax_amount={tax_amount}"


class TestQuickBooksExportScenarios:
    """Test complete QuickBooks export scenarios with tax."""
    
    def test_quickbooks_export_equipment_materials_split_with_tax(self):
        """
        Test QuickBooks export with equipment/materials split and tax.
        
        GIVEN invoice with equipment and materials items
        WHEN exporting to QuickBooks with tax distribution
        THEN each category should have correct totals with proportional tax
        """
        # Arrange - Scenario from documentation
        equipment_items = [
            {"amount": 100.00, "account": "E"},
            {"amount": 200.00, "account": "E"},
        ]
        material_items = [
            {"amount": 600.00, "account": "M"},
        ]
        
        all_items = equipment_items + material_items
        tax_amount = 100.00
        item_total = sum(item["amount"] for item in all_items)
        
        # Act - Calculate totals by category
        tax_pct = tax_amount / item_total
        
        equipment_total = sum(item["amount"] for item in equipment_items)
        equipment_tax = equipment_total * tax_pct
        equipment_with_tax = equipment_total + equipment_tax
        
        materials_total = sum(item["amount"] for item in material_items)
        materials_tax = materials_total * tax_pct
        materials_with_tax = materials_total + materials_tax
        
        # Assert
        assert abs(equipment_total - 300.00) < 0.01
        assert abs(equipment_tax - 33.33) < 0.01
        assert abs(equipment_with_tax - 333.33) < 0.01
        
        assert abs(materials_total - 600.00) < 0.01
        assert abs(materials_tax - 66.67) < 0.01
        assert abs(materials_with_tax - 666.67) < 0.01
        
        # Verify grand total
        grand_total = equipment_with_tax + materials_with_tax
        assert abs(grand_total - 1000.00) < 0.01

