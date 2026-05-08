
- Respect telegram's API rate limits. Prevent flood wait like:
  bot-1  | 2026-05-07 19:00:15,850 INFO telethon.client.users: Sleeping for 27s (0:00:27) on GetFullChannelRequest flood wait

- Multiple user's to provide channels content (now only one - admin)

- Session-file encryption (sops/age) — currently `chmod 600` only.
