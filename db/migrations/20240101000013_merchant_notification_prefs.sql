-- migrate:up
ALTER TABLE merchants
  ADD COLUMN IF NOT EXISTS notification_email_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS notification_email          TEXT;

-- migrate:down
ALTER TABLE merchants
  DROP COLUMN IF EXISTS notification_email_enabled,
  DROP COLUMN IF EXISTS notification_email;
