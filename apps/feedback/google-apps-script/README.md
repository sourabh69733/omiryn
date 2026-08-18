# Omiryn feedback Sheet

The files in this directory are the source for a Google Apps Script bound to a private Google Sheet.

Before connecting production:

1. Create a Google Sheet and open **Extensions → Apps Script**.
2. Copy `Code.gs` and run `setupFeedbackWorkbook()` once. It creates `Responses` and `Summary`.
3. Add a Script Property named `FEEDBACK_SHARED_SECRET` with a long random value.
4. Deploy the script as a web app that executes as the owner and accepts requests from anyone.
5. Configure the Cloudflare Worker secrets `GOOGLE_APPS_SCRIPT_URL` and `FEEDBACK_SHARED_SECRET`.

The Worker is the only browser-facing endpoint. Apps Script verifies the shared secret, validates every answer, blocks duplicate browser submissions for each survey version, rate limits source IP hashes, and neutralizes spreadsheet formula syntax before appending a row.
