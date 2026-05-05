from mpi_backend.database.models.Company import Company
from typing import List, Optional


class CompanyController:
    def __init__(self, db):
        self.db = db

    def get_all_companies(self) -> List[Company]:
        """Get all companies (for dropdowns, etc.)"""
        return self.db.query(Company).all()

    def get_company_by_id(self, company_id: int) -> Optional[Company]:
        """Get company by ID"""
        return self.db.query(Company).filter(Company.id == company_id).first()

    def get_company_by_name(self, name: str) -> Optional[Company]:
        """Get company by name"""
        return self.db.query(Company).filter(Company.name == name).first()

    def create_company(self, name: str) -> Optional[Company]:
        """
        Create a new company.

        Args:
            name: Company name (must be unique)

        Returns:
            Company object if successful, None if failed
        """
        try:
            # Check if company already exists
            existing = self.get_company_by_name(name)
            if existing:
                print(f"Company '{name}' already exists")
                return None

            company = Company(name=name)
            self.db.add(company)
            self.db.commit()
            return company
        except Exception as e:
            print(f"Error creating company: {e}")
            self.db.rollback()
            return None
