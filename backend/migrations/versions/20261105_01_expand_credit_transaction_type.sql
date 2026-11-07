DO $$
DECLARE
    existing_length integer;
    target_schema text := current_schema();
BEGIN
    SELECT character_maximum_length
      INTO existing_length
      FROM information_schema.columns
     WHERE table_schema = target_schema
       AND table_name = 'credit_transactions'
       AND column_name = 'transaction_type';

    -- Missing tables/columns are left to metadata.create_all on a fresh database.
    -- Unbounded or already-wide columns need no change; never shrink a column.
    IF existing_length IS NOT NULL AND existing_length < 40 THEN
        EXECUTE format(
            'ALTER TABLE %I.%I ALTER COLUMN %I TYPE VARCHAR(40)',
            target_schema,
            'credit_transactions',
            'transaction_type'
        );
    END IF;
END
$$;
