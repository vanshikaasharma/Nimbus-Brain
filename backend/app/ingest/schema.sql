-- Tiny Nimbus world. Re-run seed.py anytime. It starts from scratch.

DROP TABLE IF EXISTS invoices;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS plans;

CREATE TABLE plans (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    monthly_fee_cents INTEGER NOT NULL,
    rate_limit_rps INTEGER NOT NULL
);

CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    plan_id INTEGER NOT NULL REFERENCES plans (id)
);

CREATE TABLE invoices (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers (id),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    amount_cents INTEGER NOT NULL
);
