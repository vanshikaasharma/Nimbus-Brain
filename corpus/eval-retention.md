# Retention notes

These passages are for retrieval comparison. They are not invoices.

## Quiet hours window

The quiet hours window holds events for 15 minutes before the flush. Operators use it to batch writes. It does not change the monthly platform fee, and it is not a credit. A similar section below describes the credit that applies when events in that window are dropped.

## Quiet hours credit

When the quiet hours window drops events, the account receives a quiet hours credit of 4 percent of that month's platform fee. The credit is not the Enterprise SLA credit, and it is not the 15 minute hold described above.

## Retention ledger token

The retention ledger token is `RLT-7741`. It marks rows that stay in the ledger for 400 days. Nearby text about the quiet hours window does not contain this token.
