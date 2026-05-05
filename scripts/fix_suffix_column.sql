-- Add suffix column to suppliers table if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'suppliers' AND column_name = 'suffix'
    ) THEN
        ALTER TABLE suppliers ADD COLUMN suffix VARCHAR(10);
        
        -- Update existing suppliers with their suffixes
        UPDATE suppliers SET suffix = '-B' WHERE id = 1;  -- BMW Plumbing Supplies
        UPDATE suppliers SET suffix = '-W' WHERE id = 2;  -- World Wide Plumbing
        UPDATE suppliers SET suffix = '-Y' WHERE id = 3;  -- Y & S Plumbing Supply
        UPDATE suppliers SET suffix = '-S' WHERE id = 4;  -- Supreme Plumbing Supply
        UPDATE suppliers SET suffix = '-P' WHERE id = 5;  -- Pyramid Plumbing
        UPDATE suppliers SET suffix = '-A' WHERE id = 6;  -- ABC Opus Services
        UPDATE suppliers SET suffix = '-P' WHERE id = 7;  -- Park Plumbing Supply
        UPDATE suppliers SET suffix = '-G' WHERE id = 8;  -- Gotham Plumbing Supply
        UPDATE suppliers SET suffix = '-F' WHERE id = 9;  -- FW Webb Plumbing Supply
        UPDATE suppliers SET suffix = '-FM' WHERE id = 10; -- Flow Mark Plumbing Supply
        UPDATE suppliers SET suffix = '-PE' WHERE id = 11; -- Plumbing Exchange
        UPDATE suppliers SET suffix = '-AF' WHERE id = 12; -- AF Supply
        UPDATE suppliers SET suffix = '-L' WHERE id = 13;  -- Lion Hvac Supplies
        
        RAISE NOTICE 'Successfully added suffix column and populated data';
    ELSE
        RAISE NOTICE 'Suffix column already exists';
    END IF;
END $$;

