-- EPIC-002 / migration 0001: initial schema (TZ §3.1, §4, §5; ANCHOR_CORE §2)
-- All domain entities use surrogate INTEGER PRIMARY KEY (rowid aliases).

PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE roles (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role_id INTEGER NOT NULL REFERENCES roles(id),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE branches (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE departments (
    id INTEGER PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    name TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE divisions (
    id INTEGER PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    name TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE positions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE employment_types (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- end_date_policy: 0 = not required, 1 = required, 2 = optional (TZ §3.2)
CREATE TABLE availability_statuses (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    end_date_policy INTEGER NOT NULL DEFAULT 0 CHECK (end_date_policy IN (0, 1, 2)),
    color_hex TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE employees (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    position_id INTEGER NOT NULL REFERENCES positions(id),
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    department_id INTEGER NOT NULL REFERENCES departments(id),
    division_id INTEGER REFERENCES divisions(id),
    employment_type_id INTEGER NOT NULL REFERENCES employment_types(id),
    note TEXT,
    hire_date TEXT,
    contacts TEXT,
    home_address TEXT,
    social_insurance_number TEXT,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE status_history (
    id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    status_id INTEGER NOT NULL REFERENCES availability_statuses(id),
    start_date TEXT NOT NULL,
    end_date TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    created_by_account_id INTEGER REFERENCES accounts(id)
);

CREATE TABLE technical_events (
    id INTEGER PRIMARY KEY,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE user_action_log (
    id INTEGER PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id),
    action_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    result TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE report_templates (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('excel', 'pdf')),
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE report_template_versions (
    id INTEGER PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES report_templates(id),
    version_number INTEGER NOT NULL,
    stored_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by_account_id INTEGER REFERENCES accounts(id),
    UNIQUE (template_id, version_number)
);

CREATE INDEX idx_departments_branch ON departments(branch_id);
CREATE INDEX idx_divisions_department ON divisions(department_id);
CREATE INDEX idx_employees_branch ON employees(branch_id);
CREATE INDEX idx_employees_department ON employees(department_id);
CREATE INDEX idx_employees_full_name ON employees(full_name);
CREATE INDEX idx_status_history_employee ON status_history(employee_id);
CREATE INDEX idx_status_history_dates ON status_history(employee_id, start_date, end_date);
CREATE INDEX idx_user_action_log_created ON user_action_log(created_at);
CREATE INDEX idx_technical_events_created ON technical_events(created_at);

-- Seed: roles (TZ §4.1)
INSERT INTO roles (id, code, name) VALUES
    (1, 'administrator', 'Администратор'),
    (2, 'hr_employee', 'Сотрудник HR'),
    (3, 'observer', 'Наблюдатель');

-- Seed: employment types (TZ §3.1)
INSERT INTO employment_types (id, code, name, is_archived, created_at, updated_at) VALUES
    (1, 'staff', 'Штатный', 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z'),
    (2, 'temporary', 'Временный', 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z'),
    (3, 'contractor', 'Подрядчик', 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z');

-- Seed: availability statuses (TZ §3.2)
INSERT INTO availability_statuses (
    id, code, name, end_date_policy, color_hex, sort_order, is_archived, created_at, updated_at
) VALUES
    (1, 'office', 'В офисе', 0, '#2E6B28', 10, 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z'),
    (2, 'remote', 'Удалённо', 0, '#1E5F8C', 20, 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z'),
    (3, 'trip', 'Командировка', 1, '#9A5A12', 30, 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z'),
    (4, 'sick', 'Больничный', 2, '#A32D2D', 40, 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z'),
    (5, 'vacation', 'Отпуск', 1, '#5D3E9E', 50, 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z'),
    (6, 'day_off', 'Отгул', 1, '#8A6D06', 60, 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z'),
    (7, 'inactive', 'Уволен / неактивен', 0, '#20241F', 70, 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z');
