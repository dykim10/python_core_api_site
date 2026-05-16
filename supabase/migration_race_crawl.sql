-- review.races 테이블 크롤링 컬럼 추가
-- Supabase 대시보드 > SQL Editor 에서 실행

ALTER TABLE review.races
  ADD COLUMN IF NOT EXISTS race_time   VARCHAR(10),
  ADD COLUMN IF NOT EXISTS reg_start   DATE,
  ADD COLUMN IF NOT EXISTS reg_end     DATE,
  ADD COLUMN IF NOT EXISTS status      VARCHAR(20) DEFAULT '접수전',
  ADD COLUMN IF NOT EXISTS source      VARCHAR(30),
  ADD COLUMN IF NOT EXISTS source_url  VARCHAR(500);

-- source_url UNIQUE CONSTRAINT (upsert ON CONFLICT 에 필요)
ALTER TABLE review.races
  ADD CONSTRAINT races_source_url_key UNIQUE (source_url);
