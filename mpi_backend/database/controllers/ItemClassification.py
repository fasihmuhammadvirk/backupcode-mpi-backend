from mpi_backend.database.models import ItemClassification


class ItemClassificationController:
    def __init__(self, db):
        self.db_context = db

    def get_classification(self, item):
        query = self.db_context.query(ItemClassification).filter(ItemClassification.item == item).first()
        if query:
            if query.category == 'M':
                return 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'

            elif query.category == 'E':
                return 'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased'
            else:
                return ''
