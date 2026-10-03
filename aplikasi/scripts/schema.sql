CREATE TABLE IF NOT EXISTS documents (
  id INT AUTO_INCREMENT PRIMARY KEY,
  source_path VARCHAR(512) NOT NULL,
  file_path VARCHAR(1024) NOT NULL,
  export_path VARCHAR(1024) NULL,
  original_filename VARCHAR(255) NOT NULL,
  new_filename VARCHAR(255) NULL,
  file_sha256 VARCHAR(64) NULL,
  file_size BIGINT NULL,
  case_number VARCHAR(128) NULL,
  document_type VARCHAR(128) NULL,
  source_draft_id INT NULL,
  sipp_hearing_id BIGINT NULL,
  hearing_order INT NULL,
  hearing_date DATE NULL,
  assigned_clerk_id INT NULL,
  assigned_clerk_name VARCHAR(255) NULL,
  ocr_text MEDIUMTEXT NULL,
  ocr_engine VARCHAR(64) NULL,
  preview_path VARCHAR(1024) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'baru',
  process_started_at DATETIME NULL,
  processed_at DATETIME NULL,
  uploaded_at DATETIME NULL,
  upload_response TEXT NULL,
  error_message TEXT NULL,
  is_verified BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_documents_source_path (source_path),
  KEY ix_documents_status (status),
  KEY ix_documents_case_number (case_number),
  KEY ix_documents_document_type (document_type),
  KEY ix_documents_source_draft_id (source_draft_id),
  KEY ix_documents_sipp_hearing_id (sipp_hearing_id),
  KEY ix_documents_assigned_clerk_id (assigned_clerk_id),
  KEY ix_documents_file_sha256 (file_sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS upload_logs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  document_id INT NOT NULL,
  status VARCHAR(32) NOT NULL,
  message TEXT NULL,
  response_text TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_upload_logs_document_id (document_id),
  CONSTRAINT fk_upload_logs_document_id
    FOREIGN KEY (document_id) REFERENCES documents(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS upload_accounts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  role VARCHAR(128) NOT NULL,
  login_url VARCHAR(1024) NOT NULL,
  username VARCHAR(255) NOT NULL,
  password VARCHAR(255) NOT NULL,
  sipp_panitera_id INT NULL,
  sipp_panitera_name VARCHAR(255) NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY ix_upload_accounts_role (role),
  KEY ix_upload_accounts_sipp_panitera_id (sipp_panitera_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
