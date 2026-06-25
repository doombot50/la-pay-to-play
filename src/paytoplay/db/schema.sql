-- SQLite schema for the served Pay-to-Play database.
-- Rebuilt from scratch on each pipeline run (see db/load.py).

DROP TABLE IF EXISTS vendors;
CREATE TABLE vendors (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    address         TEXT,
    contract_total  REAL DEFAULT 0,
    contract_count  INTEGER DEFAULT 0
);

DROP TABLE IF EXISTS officials;
CREATE TABLE officials (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    office  TEXT
);

DROP TABLE IF EXISTS contracts;
CREATE TABLE contracts (
    id               TEXT PRIMARY KEY,
    vendor_id        TEXT REFERENCES vendors(id),
    amount           REAL,
    award_date       TEXT,
    awarding_agency  TEXT,
    source_url       TEXT,
    record_type      TEXT
);

-- One row per resolved DONOR ENTITY (gifts aggregated by entity_key), not per
-- individual contribution. links.donor_id references donations.id.
DROP TABLE IF EXISTS donations;
CREATE TABLE donations (
    id                TEXT PRIMARY KEY,
    donor_name        TEXT,
    employer          TEXT,
    donor_address     TEXT,
    donation_total    REAL,
    donation_count    INTEGER,
    date_first        TEXT,
    date_last         TEXT,
    recipient_name    TEXT,    -- most frequent recipient (display)
    recipient_filer   TEXT,
    recipient_office  TEXT,    -- most frequent non-empty office (display)
    source_url        TEXT
);

-- The resolved cross-dataset links + their concern scores.
DROP TABLE IF EXISTS links;
CREATE TABLE links (
    vendor_id        TEXT REFERENCES vendors(id),
    donor_id         TEXT,
    lane             TEXT,           -- org_org | org_person | address
    confidence       REAL,
    status           TEXT,           -- published | review
    contract_total   REAL,
    donation_total   REAL,
    concern_score    REAL,
    money_weight     REAL,
    control_weight   REAL,
    timing_weight    REAL,
    match_confidence REAL,
    control_office   TEXT,           -- office that drove the control weight
    agency           TEXT,           -- vendor's awarding agency (modal)
    PRIMARY KEY (vendor_id, donor_id)
);

CREATE INDEX idx_links_score  ON links(concern_score DESC);
CREATE INDEX idx_links_vendor ON links(vendor_id);
CREATE INDEX idx_contracts_vendor ON contracts(vendor_id);
