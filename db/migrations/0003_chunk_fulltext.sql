-- Full-text index on chunk text: ranked keyword search while embeddings are not available (and for hybrid search).
CREATE INDEX chunk_fts_idx ON chunk USING gin (to_tsvector('english', content));
