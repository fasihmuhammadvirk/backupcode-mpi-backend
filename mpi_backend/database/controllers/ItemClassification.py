from mpi_backend.database.models import ItemClassification
from fuzzywuzzy import fuzz


class ItemClassificationController:
    def __init__(self, db):
        self.db_context = db

    def get_classification(self, item):
        """
        Get classification for an item with fuzzy matching fallback.
        First tries exact match, then fuzzy match with 90% similarity
        threshold.
        """
        if not item or not item.strip():
            return ''

        # First try exact match
        query = (
            self.db_context.query(ItemClassification)
            .filter(ItemClassification.item == item)
            .first()
        )
        if query:
            return self._get_account_from_category(query.category)

        # If no exact match, try fuzzy matching with 90% threshold
        fuzzy_match = self._find_fuzzy_match(item, threshold=90)
        if fuzzy_match:
            return self._get_account_from_category(fuzzy_match.category)

        return ''

    def _get_account_from_category(self, category):
        """Convert category to QuickBooks account string"""
        if category == 'M':
            return 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
        elif category == 'E':
            # Fix QuickBooks account naming: singular "Equipment"
            return 'UnInvoiced JIP:Cost Of Materials:Job Equipment'
        elif category == 'A':
            return (
                'UnInvoiced JIP:Subcontractors Expense:Labor & Material:'
                'Additional Material'
            )
        else:
            return ''

    def _find_fuzzy_match(self, target_item, threshold=90):
        """
        Find fuzzy match for target item using fuzzywuzzy with specified
        threshold. Uses multiple algorithms to find the best match:
        1. partial_ratio() - for cases like "(PVC) Williams" matching "(PVC)"
        2. ratio() - for general similarity
        Returns the ItemClassification object with highest similarity
        score >= threshold.
        """
        # Get all classifications from database
        all_classifications = self.db_context.query(ItemClassification).all()

        best_match = None
        best_score = 0
        best_algorithm = ""

        for classification in all_classifications:
            if not classification.item:
                continue

            target_lower = target_item.lower().strip()
            classification_lower = classification.item.lower().strip()

            # Try different fuzzywuzzy algorithms
            algorithms = [
                (
                    'partial_ratio',
                    fuzz.partial_ratio(target_lower, classification_lower),
                ),
                (
                    'token_set_ratio',
                    fuzz.token_set_ratio(target_lower, classification_lower),
                ),
                (
                    'ratio',
                    fuzz.ratio(target_lower, classification_lower),
                ),
            ]

            # Find the best score from all algorithms
            for algorithm_name, score in algorithms:
                if score >= threshold and score > best_score:
                    best_score = score
                    best_match = classification
                    best_algorithm = algorithm_name

        if best_match:
            msg = (
                "Fuzzy match found: '{}' -> '{}' (similarity: {}% using {})"
            ).format(target_item, best_match.item, best_score, best_algorithm)
            print(msg)

        return best_match

    def get_all_classifications(self):
        """
        Get all item classifications for QuickBooks export.

        Returns:
            List of ItemClassification objects
        """
        classifications = self.db_context.query(ItemClassification).all()
        return classifications
