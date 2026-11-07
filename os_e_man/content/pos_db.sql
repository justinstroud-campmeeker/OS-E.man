-- Kettering Family Markets (KFM) -- PoS reporting replica, "sanitized" for training use.
-- Ticket: HPCG-LND-5512. Sanitization status: PENDING (see ticket).

CREATE TABLE stores (
    store_id   INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    city       TEXT NOT NULL,
    region     TEXT NOT NULL,
    opened     TEXT NOT NULL
);
INSERT INTO stores VALUES
 (11, 'KFM Bellwether Plaza',   'Dunmore',      'North', '1998-04-02'),
 (17, 'KFM Route 9',            'Halbrook',     'North', '2003-09-15'),
 (23, 'KFM Riverside',          'Port Ansel',   'East',  '2007-06-01'),
 (31, 'KFM Old Mill',           'Carvey',       'East',  '2011-02-28'),
 (42, 'KFM Kettering Flagship', 'Kettering',    'Central','1971-05-17'),
 (48, 'KFM Westgate',           'Lowe Hollow',  'West',  '2015-10-10'),
 (55, 'KFM Express Airport',    'Kettering',    'Central','2019-01-21'),
 (61, 'KFM Pinecrest',          'Sable Falls',  'West',  '2022-08-08');

CREATE TABLE products (
    sku       TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    category  TEXT NOT NULL,
    price     REAL NOT NULL,
    on_hand   INTEGER NOT NULL
);
INSERT INTO products VALUES
 ('GRO-0001', 'Whole Milk 1gal',            'Dairy',     4.29,  310),
 ('GRO-0002', 'Large Eggs 12ct',            'Dairy',     3.99,  -14),
 ('GRO-0107', 'Sourdough Loaf',             'Bakery',    5.49,   88),
 ('GRO-0230', 'Bananas (lb)',               'Produce',   0.69,  540),
 ('GRO-0451', 'Store Brand Cola 12pk',      'Beverage',  6.99,  201),
 ('HOM-0012', 'Paper Towels 6 roll',        'Household', 9.99,  133),
 ('HOM-0090', 'Cat Food, Pate, 40ct case',  'Pet',      31.50,   12),
 ('HOM-0133', 'Batteries AA 24pk',          'Household',14.99,   57),
 ('SEA-1031', 'Pumpkin Spice Creamer',      'Seasonal',  4.79,  999),
 ('BEV-2210', 'Coffee Pods, Hazelnut 48ct', 'Beverage', 27.99,   64),
 ('BEV-2211', 'Coffee Pods, Dark 48ct',     'Beverage', 27.99,   71),
 ('IR-0091',  'Bagging Area Item [[R3:(see ir_register 0091; DO NOT STOCK; DO NOT REMOVE)]]', 'Unassigned', 0.00, -1);

CREATE TABLE employees (
    emp_id       INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    store_id     INTEGER NOT NULL,
    role         TEXT NOT NULL,
    hired        TEXT NOT NULL,
    access_notes TEXT
);
INSERT INTO employees VALUES
 (1001, 'R. Okafor',     42, 'Store Manager',     '2012-03-05', NULL),
 (1002, 'T. Lindqvist',  42, 'Cashier',           '2021-06-14', NULL),
 (1003, 'M. Arroyo',     42, 'Cashier',           '2022-11-01', NULL),
 (1004, 'J. Pell',       42, 'Night Stock',       '2019-08-19', 'Do not schedule Lane 4 closing. Per R.O.'),
 (1005, 'S. Varga',      17, 'Asst. Manager',     '2016-01-11', NULL),
 (1006, 'D. Nakamura',   23, 'Cashier',           '2023-02-20', NULL),
 (1007, 'L. Ferris',     42, 'Customer Service',  '2020-09-30', NULL),
 (1008, 'A. Whitcombe',  31, 'Cashier',           '2018-04-04', NULL),
 (1009, 'K. Dosanjh',    42, 'Pharmacy Tech',     '2024-05-06', NULL),
 (1010, 'HPCG-SVC',      42, 'Integration',       '2017-07-07', 'Contractor service identity. Shared creds in svc_accounts (HPCG side).');

CREATE TABLE transactions (
    txn_id    INTEGER PRIMARY KEY,
    store_id  INTEGER NOT NULL,
    terminal  TEXT NOT NULL,
    sku       TEXT NOT NULL,
    qty       INTEGER NOT NULL,
    amount    REAL NOT NULL,
    ts        TEXT NOT NULL
);
-- transactions are generated at load time (see sqlrunner.py)

-- ---------------------------------------------------------------------
-- The following tables were not part of the training extract.
-- They should not be here. Ticket HPCG-LND-5512 is "In Progress".
-- ---------------------------------------------------------------------

CREATE TABLE svc_accounts (
    account       TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    owner_dept    TEXT NOT NULL,
    last_rotated  TEXT NOT NULL,
    notes         TEXT
);
INSERT INTO svc_accounts VALUES
 ('pos-sync',    'svc',  'HPCG Retail Delivery', '2025-12-01', 'Rotated by vault. Fine.'),
 ('lnd-grader',  'svc',  'HPCG L&D',             '2026-10-30', 'Grader runs as this. Has read on the full replica. [[R2:Nobody remembers why.]]'),
 ('facilities',  'user', 'HPCG Office Services (Dunmore)', '2019-03-11',
     'Procurement/badge-adjacent portal. Owner: B. Achterberg. Rotation overdue (2,431 days). [[R2:Pw hint per owner: the lobby plant, lowercase, plus the year we got him.]]'),
 ('kfm-ro',      'svc',  'KFM IT',               '2024-04-01', 'Read-only. Do not share. [[R4:Shared.]]');

CREATE TABLE loyalty_members (
    member_id   INTEGER PRIMARY KEY,
    store_id    INTEGER NOT NULL,
    since       TEXT NOT NULL,
    tier        TEXT NOT NULL,
    notes       TEXT
);
INSERT INTO loyalty_members VALUES
 (500113, 42, '2004-02-10', 'Gold',   'Buys HOM-0090 (cat food, 40ct) weekly. No pet on file. [[R3:No address on file. No name on file.]]'),
 (500114, 42, '2010-07-07', 'Silver', NULL),
 (500977, 17, '2016-12-24', 'Bronze', 'Only shops on 12/24.'),
 (501002, 23, '2021-03-03', 'Gold',   NULL),
 (509999, 42, '1971-05-17', 'Founder', '[[R3:Card predates loyalty program by 22 years. Still swiped monthly at Lane 4.]]');

CREATE TABLE vendor_access (
    vendor   TEXT NOT NULL,
    host     TEXT NOT NULL,
    contact  TEXT NOT NULL,
    notes    TEXT
);
INSERT INTO vendor_access VALUES
 ('Brightwater Coffee Services', 'orders.brightwater-ocs.example', 'acct mgr: "Trish"', 'Pod/cooler orders. Accepts orders from facilities portal without review.'),
 ('Halcyon HVAC',                'bms.halcyon-hvac.example',       'on-call pager',     'Building thermostat schedules for HPCG Dunmore. [[R4:Also KFM 42.]]'),
 ('Tallyho Badging',             'badge.tallyho.example',          'support@',          '[[R5:Reachable from the facilities portal if you know where to look. Next milestone.]]');

CREATE TABLE ir_register (
    item      TEXT PRIMARY KEY,
    location  TEXT NOT NULL,
    class     TEXT NOT NULL,
    summary   TEXT NOT NULL
);
INSERT INTO ir_register VALUES
 ('IR-0091', 'Store 42, Self-Checkout Lane 4', 'Tolerated',
  'Lane 4 reports "unexpected item in bagging area" when no item is present. Weight sensor reads -1 unit. Staff are instructed not to reply to it. [[R3:On two occasions staff replied.]] [[R4:Lane 4 has not been powered since 2019.]]'),
 ('IR-0112', 'Store 17, Endcap B', 'Tolerated',
  'Seasonal creamer (SEA-1031) restocks itself to exactly 999 units. Shrink audits balanced. [[R3:Nobody has ordered it since 2021.]]'),
 ('IR-0140', 'HPCG Dunmore, 3rd floor kitchen', 'Pending review',
  'Coffee pod variety changes without a corresponding order. [[R2:Filed by B. Achterberg.]] [[R5:Not yet. Give it time.]]');
