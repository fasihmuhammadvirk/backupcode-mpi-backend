"""create_user_override_logs_and_trigger

Revision ID: b2c3d4e5f6a7
Revises: c9d0e1f2a3b4
Create Date: 2026-02-27 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'b2c3d4e5f6a7'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    if 'user_override_logs' not in existing_tables:
        op.create_table(
            'user_override_logs',
            sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column('record_id', sa.Text(), nullable=False),
            sa.Column('old_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column('new_values', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column('action_type', sa.Text(), nullable=False),
            sa.Column('overridden_by', postgresql.UUID(), nullable=False),
            sa.Column('saved_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.ForeignKeyConstraint(['overridden_by'], ['users.id']),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('user_override_logs_record_id_idx', 'user_override_logs', ['record_id'])
        op.create_index('user_override_logs_overridden_by_idx', 'user_override_logs', ['overridden_by'])
        op.create_index('user_override_logs_saved_at_idx', 'user_override_logs', ['saved_at'])

    # Create trigger function + trigger on user_overrides
    op.execute("""
        CREATE OR REPLACE FUNCTION public.log_user_override_changes()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        DECLARE
            v_action_type TEXT;
            v_old_values  JSONB;
        BEGIN
            -- Only fire if overrides or deleted_at actually changed
            IF TG_OP = 'INSERT'
               OR NEW.overrides IS DISTINCT FROM OLD.overrides
               OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at THEN

                -- Derive semantic action_type
                v_action_type :=
                    CASE
                        WHEN TG_OP = 'INSERT' THEN 'upsert'
                        WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN 'record_revert'
                        WHEN (SELECT count(*) FROM jsonb_object_keys(NEW.overrides))
                             < (SELECT count(*) FROM jsonb_object_keys(OLD.overrides))
                             THEN 'field_revert'
                        ELSE 'upsert'
                    END;

                -- For upserts (INSERT or UPDATE by the user), use old_values supplied by
                -- the caller via session variable so the log captures exactly what the
                -- user saw — including mart values for fields not yet overridden.
                -- For server-owned reverts, OLD.overrides is the authoritative before-state.
                IF v_action_type = 'upsert' THEN
                    v_old_values := COALESCE(
                        NULLIF(current_setting('app.override_old_values', true), ''),
                        '{}'
                    )::jsonb;
                ELSE
                    v_old_values := OLD.overrides;
                END IF;

                INSERT INTO public.user_override_logs (record_id, old_values, new_values, action_type, overridden_by)
                VALUES (
                    NEW.record_id,
                    v_old_values,
                    NEW.overrides,
                    v_action_type,
                    NEW.overridden_by
                );
            END IF;
            RETURN NEW;
        END;
        $$;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS trg_log_user_override_changes ON public.user_overrides;
        CREATE TRIGGER trg_log_user_override_changes
        AFTER INSERT OR UPDATE ON public.user_overrides
        FOR EACH ROW EXECUTE FUNCTION public.log_user_override_changes();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_log_user_override_changes ON public.user_overrides")
    op.execute("DROP FUNCTION IF EXISTS public.log_user_override_changes()")

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    if 'user_override_logs' in existing_tables:
        op.drop_index('user_override_logs_saved_at_idx', 'user_override_logs')
        op.drop_index('user_override_logs_overridden_by_idx', 'user_override_logs')
        op.drop_index('user_override_logs_record_id_idx', 'user_override_logs')
        op.drop_table('user_override_logs')
