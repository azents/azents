---
title: "While a database transaction is open, perform only database operations; place API, Redis, broker, filesystem, and Runtime I/O outside the transaction."
---

# Database-only Transactions

- Keep open transactions within repository composition and limited to database work.
- Complete external preparation before opening a transaction; perform external effects after commit or rollback.
- Follow helper calls and injected callbacks too: an external call hidden in a helper still violates the transaction boundary.
- Verify the actual transaction lifetime. A session context may remain after commit, and a later database query may start another transaction.
- When splitting a transaction around external I/O, revalidate the database authority needed for the final write and preserve atomicity and failure handling.

## Bad

```python
async with transaction():
    record = await records.lock(record_id)
    await provider.send(record)
```

## Good

```python
intent = await delivery_repository.prepare(record_id)
result = await provider.send(intent)
await delivery_repository.finalize(intent, result)
```

Each repository operation above finishes its database-only transaction before returning.
