"""project estimate quick item seed data

Revision ID: ab0c8de7731b
Revises: 78e08818550d
Create Date: 2026-02-26 23:22:56.753917

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from sqlalchemy import Integer, String, Float, text

# revision identifiers, used by Alembic.
revision = 'ab0c8de7731b'
down_revision = '78e08818550d'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'project_estimate_point_quick_items', 'amount',
        existing_type=sa.Integer(),
        type_=sa.Float()
    )

    op.alter_column(
        'project_estimate_finish_quick_items', 'price',
        existing_type=sa.Integer(),
        type_=sa.Float()
    )

    op.alter_column(
        'project_estimate_fixed_quick_items', 'amount',
        existing_type=sa.Integer(),
        type_=sa.Float()
    )


    project_estimate_point_quick_items = table(
        'project_estimate_point_quick_items',
        column('id', Integer),
        column('name', String),
        column('amount', Float)
    )
    op.bulk_insert(project_estimate_point_quick_items,
        [
            {'id': 1, 'name': 'Toilets/Urinals', 'amount': 1},
            {'id': 2, 'name': 'Lavatories', 'amount': 1},
            {'id': 3, 'name': 'Kitchen Sinks', 'amount': 1},
            {'id': 4, 'name': 'Sinks/Fountains', 'amount': 1},
            {'id': 5, 'name': 'Tubs', 'amount': 1.5},
            {'id': 6, 'name': 'Showers', 'amount': 1.25},
            {'id': 7, 'name': 'Washers', 'amount': 1},
            {'id': 8, 'name': 'Dryers', 'amount': 0.5},
            {'id': 9, 'name': 'Gas Ranges', 'amount': 0.5},
            {'id': 10, 'name': 'Gas Meter', 'amount': 2},
            {'id': 11, 'name': 'Dishwashers', 'amount': 0},
            {'id': 12, 'name': 'Water & BBQ/Gas Lines', 'amount': 0.25},
            {'id': 13, 'name': 'Floor Heating', 'amount': 0.0025},
            {'id': 14, 'name': 'Roof drain', 'amount': 1},
            {'id': 15, 'name': 'RD risers per fl', 'amount': 0.125},
            {'id': 16, 'name': 'Drains', 'amount': 0.75},
            {'id': 17, 'name': 'AC Drains', 'amount': 0.25},
            {'id': 18, 'name': 'Sprinkler Heads', 'amount': 0.25},
            {'id': 19, 'name': 'Floor Control Valve', 'amount': 1.5},
        ]
    )

    project_estimate_fixed_quick_items = table(
        'project_estimate_fixed_quick_items',
        column('id', Integer),
        column('name', String),
        column('amount', Float)
    )
    op.bulk_insert(project_estimate_fixed_quick_items,
        [
            {'id': 1, 'name': 'Equipment Cost', 'amount': 0},
            {'id': 2, 'name': 'Insulation', 'amount': 0},
            {'id': 3, 'name': 'Firestopping', 'amount': 0},
            {'id': 4, 'name': 'Welding', 'amount': 0},
            {'id': 5, 'name': 'RPZ', 'amount': 0},
            {'id': 6, 'name': 'Boiler/ Heating Systems', 'amount': 0},
            {'id': 7, 'name': 'Elevator/Storm Pumps', 'amount': 0},
            {'id': 8, 'name': 'Sewage Ejector Pumps', 'amount': 0},
            {'id': 9, 'name': 'Water Booster Pumps', 'amount': 0},
            {'id': 10, 'name': 'Gas Booster Pumps', 'amount': 0},
            {'id': 11, 'name': 'PRV', 'amount': 0},
            {'id': 12, 'name': 'Sprinkler Jockey Pumps', 'amount': 0},
            {'id': 13, 'name': 'Other', 'amount': 0},
        ]
    )

    project_estimate_finish_quick_items = table(
        'project_estimate_finish_quick_items',
        column('id', Integer),
        column('name', String),
        column('price', Float)
    )
    op.bulk_insert(project_estimate_finish_quick_items,
        [
            {'id': 1, 'name': 'Toilets/Urinals', 'price': 100},
            {'id': 2, 'name': 'Lavatories', 'price': 100},
            {'id': 3, 'name': 'Kitchen Sinks', 'price': 100},
            {'id': 4, 'name': 'Sinks/Fountains', 'price': 100},
            {'id': 5, 'name': 'Tubs', 'price': 100},
            {'id': 6, 'name': 'Showers', 'price': 100},
            {'id': 7, 'name': 'Washers/Dryers', 'price': 50},
            {'id': 8, 'name': 'Dishwashers/Gas Ranges', 'price': 35},
            {'id': 9, 'name': 'Water & BBQ/Gas Lines', 'price': 100},
            {'id': 10, 'name': 'Floor Heating', 'price': 100},
            {'id': 11, 'name': 'Roof drain', 'price': 100},
            {'id': 12, 'name': 'RD risers per fl', 'price': 100},
            {'id': 13, 'name': 'Drains', 'price': 100},
            {'id': 14, 'name': 'AC Drains', 'price': 100},
            {'id': 15, 'name': 'Sprinkler Covers', 'price': 3},
            {'id': 16, 'name': 'Floor Control Valve', 'price': 100},
            {'id': 17, 'name': 'Change orders', 'price': 100},
        ]
    )

def downgrade():
    # Reverse the changes
    op.execute(text("DELETE FROM public.project_estimate_point_quick_items"))
    op.execute(text("DELETE FROM public.project_estimate_fixed_quick_items"))
    op.execute(text("DELETE FROM public.project_estimate_finish_quick_items"))

    # Revert column types from Float back to Integer
    op.alter_column(
        'project_estimate_point_quick_items', 'amount',
        existing_type=sa.Float(),
        type_=sa.Integer()
    )

    op.alter_column(
        'project_estimate_finish_quick_items', 'price',
        existing_type=sa.Float(),
        type_=sa.Integer()
    )

    op.alter_column(
        'project_estimate_fixed_quick_items', 'amount',
        existing_type=sa.Float(),
        type_=sa.Integer()
    )