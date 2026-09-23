-- W09 财报 Agent 数据地基 schema
-- 数据库由 init_db.py 用 pymysql 执行（无需 mysql CLI）
CREATE DATABASE IF NOT EXISTS fin_agent
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE fin_agent;

CREATE TABLE IF NOT EXISTS fin_companies (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(16) NOT NULL COMMENT '股票代码 如 600519',
  name VARCHAR(128) NOT NULL,
  exchange VARCHAR(8) DEFAULT 'SH' COMMENT 'SH/SZ',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_code (code)
) ENGINE=InnoDB COMMENT='公司主表';

CREATE TABLE IF NOT EXISTS fin_reports (
  id INT AUTO_INCREMENT PRIMARY KEY,
  company_id INT NOT NULL,
  year INT NOT NULL COMMENT '报告年度',
  report_type VARCHAR(16) DEFAULT 'annual' COMMENT 'annual/interim',
  raw_file VARCHAR(255) DEFAULT NULL COMMENT '原始文件',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_company (company_id),
  CONSTRAINT fk_report_company FOREIGN KEY (company_id) REFERENCES fin_companies(id)
) ENGINE=InnoDB COMMENT='报告期';

CREATE TABLE IF NOT EXISTS fin_indicators (
  code VARCHAR(32) NOT NULL PRIMARY KEY COMMENT '标准科目 code 如 NP_DEDUCT',
  name VARCHAR(128) NOT NULL COMMENT '标准名',
  aliases JSON NOT NULL COMMENT '别名数组',
  unit_standard VARCHAR(16) DEFAULT '元' COMMENT '标准单位',
  unit_convert DECIMAL(20,6) DEFAULT 1 COMMENT '原始单位->标准单位乘数',
  confusing_group VARCHAR(32) DEFAULT NULL COMMENT '易混淆组',
  requires_modifier_guard TINYINT(1) DEFAULT 0 COMMENT '否定词保护',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB COMMENT='字段字典(单一真相源)';

CREATE TABLE IF NOT EXISTS fin_report_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  report_id INT NOT NULL,
  raw_name VARCHAR(255) NOT NULL COMMENT '抽取到的原始科目名',
  matched_code VARCHAR(32) DEFAULT NULL COMMENT '命中字典 code',
  value DECIMAL(28,6) DEFAULT NULL,
  unit VARCHAR(16) DEFAULT NULL,
  page INT DEFAULT NULL,
  confidence DECIMAL(5,4) DEFAULT NULL COMMENT '0-1',
  method VARCHAR(8) DEFAULT NULL COMMENT 'L1/L2/L3/L4/L0',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_report (report_id),
  KEY idx_code (matched_code),
  CONSTRAINT fk_item_report FOREIGN KEY (report_id) REFERENCES fin_reports(id),
  CONSTRAINT fk_item_indicator FOREIGN KEY (matched_code) REFERENCES fin_indicators(code)
) ENGINE=InnoDB COMMENT='抽取落库(已精准识别)';

CREATE TABLE IF NOT EXISTS fin_indicator_unknown (
  id INT AUTO_INCREMENT PRIMARY KEY,
  raw_name VARCHAR(255) NOT NULL,
  report_id INT DEFAULT NULL,
  page INT DEFAULT NULL,
  reason VARCHAR(255) DEFAULT NULL COMMENT '未命中原因',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_report (report_id)
) ENGINE=InnoDB COMMENT='未匹配队列(单独表,不污染精准数据)';
