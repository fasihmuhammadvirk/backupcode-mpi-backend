"""add_is_row_deleted_to_user_overrides

Adds a boolean flag to public.user_overrides so that individual mart rows
can be soft-deleted without touching the mart table itself.

When is_row_deleted = TRUE the row is excluded from all data-review queries
and aggregations.  The existing overrides JSONB is preserved so that any
field-level edits come back automatically when the row is restored.

Revision ID: a1b2c3d4e5f6
Revises: 307c23e98f20
Create Date: 2026-04-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = '4c2b9881580d'
branch_labels = None
depends_on = None


def upgrade():
    # ---------------------------------------------------------------------------
    # 1. Add is_row_deleted column
    # ---------------------------------------------------------------------------
    op.add_column(
        'user_overrides',
        sa.Column(
            'is_row_deleted',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )

    # ---------------------------------------------------------------------------
    # 2. Partial index — fast lookup of deleted rows (sparse; most rows = FALSE)
    # ---------------------------------------------------------------------------
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS user_overrides_row_deleted_idx
            ON public.user_overrides (record_id)
            WHERE is_row_deleted = TRUE
        """
    )

    # ---------------------------------------------------------------------------
    # 3. Update the audit trigger to emit 'row_delete' / 'row_restore' action
    #    types when is_row_deleted transitions.  All other logic is unchanged.
    # ---------------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION public.log_user_override_changes()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        DECLARE
            v_action_type TEXT;
            v_old_values  JSONB;
        BEGIN
            -- Only fire if overrides, deleted_at, or is_row_deleted actually changed
            IF TG_OP = 'INSERT'
               OR NEW.overrides       IS DISTINCT FROM OLD.overrides
               OR NEW.deleted_at      IS DISTINCT FROM OLD.deleted_at
               OR NEW.is_row_deleted  IS DISTINCT FROM OLD.is_row_deleted THEN

                -- Derive semantic action_type
                v_action_type :=
                    CASE
                        WHEN TG_OP = 'INSERT'                              THEN 'upsert'
                        WHEN NEW.is_row_deleted = TRUE
                             AND (OLD.is_row_deleted IS NULL
                                  OR OLD.is_row_deleted = FALSE)           THEN 'row_delete'
                        WHEN NEW.is_row_deleted = FALSE
                             AND OLD.is_row_deleted = TRUE                 THEN 'row_restore'
                        WHEN NEW.deleted_at IS NOT NULL
                             AND OLD.deleted_at IS NULL                    THEN 'record_revert'
                        WHEN (SELECT count(*) FROM jsonb_object_keys(NEW.overrides))
                             < (SELECT count(*) FROM jsonb_object_keys(OLD.overrides))
                                                                           THEN 'field_revert'
                        ELSE 'upsert'
                    END;

                -- For upserts use old_values supplied by the caller via session variable
                -- so the log captures exactly what the user saw.
                -- For server-owned operations use OLD.overrides as the authoritative
                -- before-state.
                IF v_action_type = 'upsert' THEN
                    v_old_values := COALESCE(
                        NULLIF(current_setting('app.override_old_values', true), ''),
                        '{}'
                    )::jsonb;
                ELSE
                    v_old_values := COALESCE(OLD.overrides, '{}'::jsonb);
                END IF;

                INSERT INTO public.user_override_logs
                    (record_id, old_values, new_values, action_type, overridden_by)
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

    # Re-attach the trigger (CREATE OR REPLACE on the function is enough, but
    # we drop and recreate to be safe in case the trigger definition ever changes).
    op.execute("""
        DROP TRIGGER IF EXISTS trg_log_user_override_changes ON public.user_overrides;
        CREATE TRIGGER trg_log_user_override_changes
        AFTER INSERT OR UPDATE ON public.user_overrides
        FOR EACH ROW EXECUTE FUNCTION public.log_user_override_changes();
    """)


def downgrade():
    # Restore previous trigger function (without is_row_deleted awareness)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.log_user_override_changes()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        DECLARE
            v_action_type TEXT;
            v_old_values  JSONB;
        BEGIN
            IF TG_OP = 'INSERT'
               OR NEW.overrides IS DISTINCT FROM OLD.overrides
               OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at THEN

                v_action_type :=
                    CASE
                        WHEN TG_OP = 'INSERT' THEN 'upsert'
                        WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN 'record_revert'
                        WHEN (SELECT count(*) FROM jsonb_object_keys(NEW.overrides))
                             < (SELECT count(*) FROM jsonb_object_keys(OLD.overrides))
                             THEN 'field_revert'
                        ELSE 'upsert'
                    END;

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

    op.execute("DROP INDEX IF EXISTS user_overrides_row_deleted_idx")
    op.drop_column('user_overrides', 'is_row_deleted')
