-- ══════════════════════════════════════════════════════════════════════════════
-- 037 — Supervisor-assigned tasks with per-task custom checklists.
-- Supervisor creates a task (title/desc/location/priority/due), attaches custom
-- checklist items, and assigns it to one or more workers. Each worker fills their
-- own copy (Yes/No + description per item). Manager can view all + edit checklist.
-- ══════════════════════════════════════════════════════════════════════════════

-- The task itself
CREATE TABLE IF NOT EXISTS assigned_tasks (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id INT          NULL,
    title           VARCHAR(255) NOT NULL,
    description     TEXT         NULL,
    location        VARCHAR(255) NULL,
    priority        VARCHAR(20)  NOT NULL DEFAULT 'medium',   -- low / medium / high
    due_at          DATETIME     NULL,
    assigned_by     INT          NULL,                         -- supervisor employee id
    status          VARCHAR(30)  NOT NULL DEFAULT 'active',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_assigned_tasks_org (organisation_id),
    INDEX idx_assigned_tasks_by (assigned_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Custom checklist items the supervisor defines for the task
CREATE TABLE IF NOT EXISTS assigned_task_items (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    task_id     INT          NOT NULL,
    item_no     INT          NOT NULL DEFAULT 1,
    item_text   VARCHAR(500) NOT NULL,
    is_required TINYINT(1)   NOT NULL DEFAULT 1,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ati_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Which workers the task is assigned to (many per task) + their fill status
CREATE TABLE IF NOT EXISTS assigned_task_workers (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    task_id            INT         NOT NULL,
    worker_employee_id INT         NOT NULL,
    status             VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending / filled
    filled_at          DATETIME    NULL,
    created_at         DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_atw_task (task_id),
    INDEX idx_atw_worker (worker_employee_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- A worker's filled answers (Yes/No + description) per checklist item
CREATE TABLE IF NOT EXISTS assigned_task_responses (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    task_id            INT         NOT NULL,
    worker_employee_id INT         NOT NULL,
    item_id            INT         NOT NULL,
    answer             VARCHAR(10) NULL,      -- 'Yes' / 'No'
    description        TEXT        NULL,
    created_at         DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_atr_task (task_id),
    UNIQUE KEY uq_atr_worker_item (worker_employee_id, item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
