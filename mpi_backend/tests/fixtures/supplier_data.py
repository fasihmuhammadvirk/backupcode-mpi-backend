"""
Test data factories for supplier-related entities.

Provides reusable test data builders for suppliers and supplier mappings.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List


class SupplierFactory:
    """Factory for creating test supplier data."""
    
    @staticmethod
    def create(
        id: Optional[int] = None,
        supplier_name: str = "Test Supplier",
        supplier_type: str = "plumbing",
        is_active: bool = True,
        created_at: Optional[datetime] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a test supplier.
        
        Args:
            id: Supplier ID
            supplier_name: Supplier name
            supplier_type: Type of supplier
            is_active: Is active flag
            created_at: Creation timestamp
            **kwargs: Additional fields
            
        Returns:
            Dictionary with supplier data
        """
        return {
            "id": 1 if id is None else id,
            "supplier_name": supplier_name,
            "supplier_type": supplier_type,
            "is_active": is_active,
            "created_at": created_at or datetime.now(),
            **kwargs
        }
    
    @staticmethod
    def create_multiple(count: int, **base_kwargs) -> List[Dict[str, Any]]:
        """
        Create multiple suppliers.
        
        Args:
            count: Number of suppliers to create
            **base_kwargs: Base attributes for all suppliers
            
        Returns:
            List of supplier dictionaries
        """
        suppliers = []
        for i in range(count):
            supplier_kwargs = base_kwargs.copy()
            supplier_kwargs['id'] = i + 1
            supplier_kwargs['supplier_name'] = supplier_kwargs.get(
                'supplier_name',
                f'Test Supplier {chr(65 + i)}'  # A, B, C, etc.
            )
            suppliers.append(SupplierFactory.create(**supplier_kwargs))
        return suppliers


class SupplierMappingFactory:
    """Factory for creating test supplier item mapping data."""
    
    @staticmethod
    def create(
        id: Optional[int] = None,
        supplier_id: int = 1,
        supplier_item: str = "SUPP-ITEM-001",
        supplier_description: str = "Supplier Item Description",
        mpi_item: str = "MPI-ITEM-001",
        mpi_description: str = "MPI Item Description",
        mapping_type: str = "manual",
        confidence: float = 1.0,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a test supplier item mapping.
        
        Args:
            id: Mapping ID
            supplier_id: Supplier ID
            supplier_item: Supplier item code
            supplier_description: Supplier item description
            mpi_item: MPI item code
            mpi_description: MPI item description
            mapping_type: Type of mapping (manual, auto, fuzzy)
            confidence: Confidence score (0.0 to 1.0)
            created_at: Creation timestamp
            updated_at: Update timestamp
            **kwargs: Additional fields
            
        Returns:
            Dictionary with supplier mapping data
        """
        return {
            "id": id or 1,
            "supplier_id": supplier_id,
            "supplier_item": supplier_item,
            "supplier_description": supplier_description,
            "mpi_item": mpi_item,
            "mpi_description": mpi_description,
            "mapping_type": mapping_type,
            "confidence": confidence,
            "created_at": created_at or datetime.now(),
            "updated_at": updated_at or datetime.now(),
            **kwargs
        }
    
    @staticmethod
    def create_multiple(count: int, supplier_id: int = 1, **base_kwargs) -> List[Dict[str, Any]]:
        """
        Create multiple supplier mappings.
        
        Args:
            count: Number of mappings to create
            supplier_id: Supplier ID for all mappings
            **base_kwargs: Base attributes for all mappings
            
        Returns:
            List of supplier mapping dictionaries
        """
        mappings = []
        for i in range(count):
            mapping_kwargs = base_kwargs.copy()
            mapping_kwargs['id'] = i + 1
            mapping_kwargs['supplier_id'] = supplier_id
            mapping_kwargs['supplier_item'] = mapping_kwargs.get(
                'supplier_item',
                f'SUPP-{i+1:03d}'
            )
            mapping_kwargs['mpi_item'] = mapping_kwargs.get(
                'mpi_item',
                f'MPI-{i+1:03d}'
            )
            mappings.append(SupplierMappingFactory.create(**mapping_kwargs))
        return mappings


class ItemClassificationFactory:
    """Factory for creating test item classification data."""
    
    @staticmethod
    def create(
        id: Optional[int] = None,
        item: str = "Test Item",
        category: str = "M",  # M=Materials, E=Equipment, L=Labor
        description: Optional[str] = None,
        created_at: Optional[datetime] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a test item classification.
        
        Args:
            id: Classification ID
            item: Item name/code
            category: Category (M, E, L)
            description: Description
            created_at: Creation timestamp
            **kwargs: Additional fields
            
        Returns:
            Dictionary with item classification data
        """
        return {
            "id": id or 1,
            "item": item,
            "category": category,
            "description": description or f"{item} - {category}",
            "created_at": created_at or datetime.now(),
            **kwargs
        }
    
    @staticmethod
    def create_materials(item: str = "Material Item", **kwargs) -> Dict[str, Any]:
        """Create a materials classification."""
        return ItemClassificationFactory.create(
            item=item,
            category="M",
            **kwargs
        )
    
    @staticmethod
    def create_equipment(item: str = "Equipment Item", **kwargs) -> Dict[str, Any]:
        """Create an equipment classification."""
        return ItemClassificationFactory.create(
            item=item,
            category="E",
            **kwargs
        )
    
    @staticmethod
    def create_labor(item: str = "Labor Item", **kwargs) -> Dict[str, Any]:
        """Create a labor classification."""
        return ItemClassificationFactory.create(
            item=item,
            category="L",
            **kwargs
        )


# Preset scenarios for common test cases
class SupplierScenarios:
    """Predefined supplier scenarios for testing."""
    
    @staticmethod
    def common_suppliers() -> List[Dict[str, Any]]:
        """
        Create common supplier test data.

        Returns:
            List of common supplier dictionaries
        """
        return [
            SupplierFactory.create(
                id=0,
                supplier_name="Unknown Supplier",
                supplier_type="plumbing",
                suffix=None
            ),
            SupplierFactory.create(
                id=1,
                supplier_name="BMW Plumbing Supplies",
                supplier_type="plumbing"
            ),
            SupplierFactory.create(
                id=2,
                supplier_name="Flow Mark",
                supplier_type="plumbing"
            ),
            SupplierFactory.create(
                id=3,
                supplier_name="World Wide Plumbing",
                supplier_type="plumbing"
            ),
            SupplierFactory.create(
                id=4,
                supplier_name="Supreme Plumbing",
                supplier_type="plumbing"
            ),
            SupplierFactory.create(
                id=5,
                supplier_name="AF Supply",
                supplier_type="plumbing"
            ),
        ]
    
    @staticmethod
    def supplier_with_mappings(
        supplier_id: int = 1,
        mapping_count: int = 5
    ) -> Dict[str, Any]:
        """
        Create supplier with item mappings.
        
        Args:
            supplier_id: Supplier ID
            mapping_count: Number of mappings to create
            
        Returns:
            Dictionary with supplier and mappings
        """
        supplier = SupplierFactory.create(
            id=supplier_id,
            supplier_name="BMW Plumbing Supplies"
        )
        
        mappings = SupplierMappingFactory.create_multiple(
            mapping_count,
            supplier_id=supplier_id
        )
        
        return {
            "supplier": supplier,
            "mappings": mappings
        }
    
    @staticmethod
    def classification_scenarios() -> Dict[str, List[Dict[str, Any]]]:
        """
        Create item classification scenarios for testing.
        
        Returns:
            Dictionary with classification categories
        """
        return {
            "materials": [
                ItemClassificationFactory.create_materials(item="Pipe Fitting"),
                ItemClassificationFactory.create_materials(item="Valve"),
                ItemClassificationFactory.create_materials(item="Connector"),
            ],
            "equipment": [
                ItemClassificationFactory.create_equipment(item="Power Tool"),
                ItemClassificationFactory.create_equipment(item="Safety Equipment"),
                ItemClassificationFactory.create_equipment(item="Measuring Device"),
            ],
            "labor": [
                ItemClassificationFactory.create_labor(item="Installation Service"),
                ItemClassificationFactory.create_labor(item="Repair Service"),
                ItemClassificationFactory.create_labor(item="Consultation"),
            ],
        }
    
    @staticmethod
    def uidi_items() -> List[Dict[str, Any]]:
        """
        Create UIDI (unidentified) item scenarios.
        
        Returns:
            List of UIDI item classifications
        """
        return [
            ItemClassificationFactory.create(
                item="UIDI-JOB MATERIALS PURCHASED",
                category="M",
                description="Unidentified job materials"
            ),
            ItemClassificationFactory.create(
                item="UIDI JOB MATERIAL",
                category="M",
                description="Unidentified job material"
            ),
            ItemClassificationFactory.create(
                item="UIDI-JOB EQUIPMENT",
                category="E",
                description="Unidentified job equipment"
            ),
            ItemClassificationFactory.create(
                item="UIDI-SPRINKLER SPECIALTY ITEM",
                category="M",
                description="Unidentified sprinkler specialty item"
            ),
            ItemClassificationFactory.create(
                item="UIDI-DRAINAGE MATERIAL",
                category="M",
                description="Unidentified drainage material"
            ),
        ]

