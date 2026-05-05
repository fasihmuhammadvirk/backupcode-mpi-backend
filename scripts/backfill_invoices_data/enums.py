"""Supplier enums and extraction function mappings."""
from enum import Enum
from typing import Callable, Optional


class SupplierName(str, Enum):
    """Supplier name enumeration for invoice processing."""
    ABC_OPUS_SERVICES = "ABC Opus Services"
    AF_SUPPLY = "AF Supply"
    BMW_PLUMBING_SUPPLIES = "BMW Plumbing Supplies"
    FERGUSON = "Ferguson"
    FLOW_MARK_PLUMBING_SUPPLY = "Flow Mark Plumbing Supply"
    FW_WEBB_PLUMBING_SUPPLY = "F.W. Webb Plumbing Supply"
    GOTHAM_PIPE_SUPPLY = "Gotham Pipe Supply, LLC"
    LION_HVAC_SUPPLIES = "Lion Hvac Supplies"
    PLUMBING_EXCHANGE = "Plumbing Exchange"
    SUPREME_PLUMBING_SUPPLY = "Supreme Plumbing Supply"
    WORLD_WIDE_PLUMBING = "World Wide Plumbing"
    Y_AND_S_PLUMBING_SUPPLIES = "Y & S Plumbing Supplies"
    YYBUNKER_HVAC = "YYBUNKER HVAC LLC"
    BRUCE_SUPPLY_CORP = "Bruce Supply Corp."
    
    @classmethod
    def values(cls) -> list[str]:
        """Return list of all valid supplier name values."""
        return [supplier.value for supplier in cls]
    
    @classmethod
    def from_vendor_name(cls, vendor_name: str) -> Optional["SupplierName"]:
        """Get SupplierName enum from vendor name string with alias support."""
        for supplier in cls:
            if supplier.value.lower() == vendor_name.lower():
                return supplier
        
        vendor_aliases = {
            "bmw plumbing": cls.BMW_PLUMBING_SUPPLIES,
            "bmw": cls.BMW_PLUMBING_SUPPLIES,
            "gotham plumbing supply": cls.GOTHAM_PIPE_SUPPLY,
            "gotham supply": cls.GOTHAM_PIPE_SUPPLY,
            "gotham": cls.GOTHAM_PIPE_SUPPLY,
            "fw webb plumbing supply": cls.FW_WEBB_PLUMBING_SUPPLY,
            "fw webb": cls.FW_WEBB_PLUMBING_SUPPLY,
            "web co supply": cls.FW_WEBB_PLUMBING_SUPPLY,
            "y & s plumbing supply": cls.Y_AND_S_PLUMBING_SUPPLIES,
            "y&s plumbing": cls.Y_AND_S_PLUMBING_SUPPLIES,
            "ys plumbing": cls.Y_AND_S_PLUMBING_SUPPLIES,
            "flowmark plumbing supply": cls.FLOW_MARK_PLUMBING_SUPPLY,
            "flowmark": cls.FLOW_MARK_PLUMBING_SUPPLY,
            "supreme plumbing": cls.SUPREME_PLUMBING_SUPPLY,
            "supreme": cls.SUPREME_PLUMBING_SUPPLY,
            "lion hvac": cls.LION_HVAC_SUPPLIES,
            "lion havac": cls.LION_HVAC_SUPPLIES,
            "abc opus": cls.ABC_OPUS_SERVICES,
            "worldwide plumbing": cls.WORLD_WIDE_PLUMBING,
            "world wide": cls.WORLD_WIDE_PLUMBING,
            "wwp": cls.WORLD_WIDE_PLUMBING,
            "yybunker hvac": cls.YYBUNKER_HVAC,
            "yybunker": cls.YYBUNKER_HVAC,
        }
        
        return vendor_aliases.get(vendor_name.lower().strip())


ExtractionFunction = Callable[[str, str], None]


def get_extraction_function(supplier: SupplierName) -> Optional[ExtractionFunction]:
    """Get the tabula extraction function for a given supplier."""
    from tabula_extraction.bmw_old import process_invoice as bmw_process_invoice
    from tabula_extraction.abc_opus_services_utils import process_invoice as abc_opus_process_invoice
    from tabula_extraction.af_supply import process_invoice as af_supply_process_invoice
    from tabula_extraction.ferguson import extract_ferguson_invoices_data
    from tabula_extraction.flow_mark import process_invoice as flow_mark_process_invoice
    from tabula_extraction.gotham_supply import process_invoice as gotham_process_invoice
    from tabula_extraction.lion_havac import process_invoice as lion_hvac_process_invoice
    from tabula_extraction.plumbing_exchange import process_invoice as plumbing_exchange_process_invoice
    from tabula_extraction.supremePlumbing_uitl import extract_supremePlumbing_data
    from tabula_extraction.web_co_supply import process_invoice as web_co_process_invoice
    from tabula_extraction.world_wide_plumbing import process_invoice as world_wide_plumbing_process_invoice
    from tabula_extraction.ys_old import process_invoice as ys_process_invoice
    from tabula_extraction.yybunker_hvac import process_invoice as yybunker_process_invoice
    
    extraction_functions: dict[SupplierName, ExtractionFunction] = {
        SupplierName.ABC_OPUS_SERVICES: abc_opus_process_invoice,
        SupplierName.AF_SUPPLY: af_supply_process_invoice,
        SupplierName.BMW_PLUMBING_SUPPLIES: bmw_process_invoice,
        SupplierName.FERGUSON: extract_ferguson_invoices_data,
        SupplierName.FLOW_MARK_PLUMBING_SUPPLY: flow_mark_process_invoice,
        SupplierName.FW_WEBB_PLUMBING_SUPPLY: web_co_process_invoice,
        SupplierName.GOTHAM_PIPE_SUPPLY: gotham_process_invoice,
        SupplierName.LION_HVAC_SUPPLIES: lion_hvac_process_invoice,
        SupplierName.PLUMBING_EXCHANGE: plumbing_exchange_process_invoice,
        SupplierName.SUPREME_PLUMBING_SUPPLY: extract_supremePlumbing_data,
        SupplierName.WORLD_WIDE_PLUMBING: world_wide_plumbing_process_invoice,
        SupplierName.Y_AND_S_PLUMBING_SUPPLIES: ys_process_invoice,
        SupplierName.YYBUNKER_HVAC: yybunker_process_invoice,
    }
    
    return extraction_functions.get(supplier)


SUPPLIER_MODULE_MAP: dict[SupplierName, str] = {
    SupplierName.ABC_OPUS_SERVICES: "abc_opus_services_utils",
    SupplierName.AF_SUPPLY: "af_supply",
    SupplierName.BMW_PLUMBING_SUPPLIES: "bmw_old",
    SupplierName.FERGUSON: "ferguson",
    SupplierName.FLOW_MARK_PLUMBING_SUPPLY: "flow_mark",
    SupplierName.FW_WEBB_PLUMBING_SUPPLY: "web_co_supply",
    SupplierName.GOTHAM_PIPE_SUPPLY: "gotham_supply",
    SupplierName.LION_HVAC_SUPPLIES: "lion_havac",
    SupplierName.PLUMBING_EXCHANGE: "plumbing_exchange",
    SupplierName.SUPREME_PLUMBING_SUPPLY: "supremePlumbing_uitl",
    SupplierName.WORLD_WIDE_PLUMBING: "world_wide_plumbing",
    SupplierName.Y_AND_S_PLUMBING_SUPPLIES: "ys_old",
    SupplierName.YYBUNKER_HVAC: "yybunker_hvac",
}


def process_invoice_by_supplier(supplier_name: str, filename: str, output_path: str) -> bool:
    """Process an invoice using the appropriate supplier-specific extraction function."""
    supplier = SupplierName.from_vendor_name(supplier_name)
    if supplier is None:
        return False
    
    extraction_func = get_extraction_function(supplier)
    if extraction_func is None:
        return False
    
    try:
        extraction_func(filename, output_path)
        return True
    except Exception:
        return False

# AI Model names
GEMINI_MODEL = "gemini-2.5-pro"
OPENAI_GPT_4_1_MINI = "gpt-4.1-mini"
TABULA = "tabula"

# List of all available models
ALL_MODELS = [GEMINI_MODEL]#, OPENAI_GPT_4_1_MINI, TABULA]
