-- 0009: keyword index of document_chunks, computed by the database.
-- 0007 created document_chunks.tsv as a plain column that nothing filled (0 of 148,342 rows), so keyword search
-- would have to compute to_tsvector over every chunk on every query. tsv becomes a generated column: PostgreSQL
-- fills it from content in the chunk's own language whenever a chunk is written. One definition, never stale.

-- the text-search configuration for a chunk language (ISO 639-1); 'simple' splits words without stemming
-- (Thai and Malay have no PostgreSQL stemmer)
CREATE FUNCTION chunk_ts_config(lang TEXT) RETURNS regconfig
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE lang WHEN 'en' THEN 'english'::regconfig ELSE 'simple'::regconfig END
$$;

ALTER TABLE document_chunks DROP COLUMN tsv;   -- its index goes with it
ALTER TABLE document_chunks
  ADD COLUMN tsv tsvector GENERATED ALWAYS AS (to_tsvector(chunk_ts_config(language), content)) STORED;
CREATE INDEX document_chunks_tsv_idx ON document_chunks USING gin (tsv);
