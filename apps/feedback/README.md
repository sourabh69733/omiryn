# Omiryn feedback app

Cloudflare D1 is the authoritative and only active submission store.

## D1 setup

1. Create a D1 database named `omiryn-feedback` in Cloudflare.
2. Add its binding to `wrangler.jsonc` with the binding name `FEEDBACK_DB`.
3. Deploy with `npm run feedback:deploy`. It applies pending migrations before
   publishing the Worker.

The binding block has this shape:

```jsonc
"d1_databases": [
  {
    "binding": "FEEDBACK_DB",
    "database_name": "omiryn-feedback",
    "database_id": "<ID shown by Cloudflare>",
    "migrations_dir": "./migrations"
  }
]
```

`FEEDBACK_SHARED_SECRET` remains a required Worker secret because it salts the
stored IP and browser-token hashes. Raw identifiers are never written to D1.
