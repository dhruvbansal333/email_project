-- Multi-user extension, Task 4: one small schema addition.
-- Lets the API find a user by their API key's hash instantly, and guarantees
-- two users can never hold the same key. Safe to run more than once.
CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
