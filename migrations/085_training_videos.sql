-- ─────────────────────────────────────────────────────────────────────────────
-- 085 · Training videos (admin-curated, role-targeted) + comments
--
-- Replaces the old /worker/training stub (backed by training_programs, which
-- has no video/description/audience field and is kept for its own unrelated
-- WF-06 competence/analytics uses — see app/models/training_program.py). Admin
-- uploads a video link per training_videos row, targets it at one or more of
-- the mobile app's 4 role buckets (worker/supervisor/manager/auditor) via the
-- JSON-array target_roles column, and every targeted role can discuss it in
-- training_video_comments. See app/models/training_video.py.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS training_videos (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organisation_id INT NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT NULL,
  video_url VARCHAR(500) NOT NULL,
  target_roles TEXT NOT NULL COMMENT 'JSON array of worker|supervisor|manager|auditor',
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY ix_training_videos_org (organisation_id)
);

CREATE TABLE IF NOT EXISTS training_video_comments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organisation_id INT NULL,
  training_video_id INT NOT NULL,
  comment_text TEXT NOT NULL,
  author_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY ix_training_video_comments_video (training_video_id),
  CONSTRAINT fk_training_video_comments_video FOREIGN KEY (training_video_id)
    REFERENCES training_videos (id) ON DELETE CASCADE
);
