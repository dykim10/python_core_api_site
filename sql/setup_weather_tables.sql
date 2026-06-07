-- ============================================================
-- PAC-RUN CORE API — 날씨 관련 테이블 설정
-- 대상 스키마: review
-- 실행: Supabase SQL Editor (로컬 / LIVE 각각 1회 실행)
-- ============================================================

-- review 스키마 없으면 생성
CREATE SCHEMA IF NOT EXISTS review;


-- ──────────────────────────────────────────────────────────
-- 1. weather_stations — 기상청 관측소 지점 정보
--    기상청 stn_inf.php API 에서 수신한 원본 데이터를 그대로 저장
-- ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS review.weather_stations (
    id         BIGSERIAL      PRIMARY KEY,
    stn_id     INTEGER        NOT NULL,           -- 기상청 지점코드 (예: 108)
    stn_name   VARCHAR(50),                       -- 지점명 (예: 서울)
    lat        NUMERIC(9, 4),                     -- 위도
    lon        NUMERIC(9, 4),                     -- 경도
    ht         NUMERIC(8, 2),                     -- 고도 (m)
    fetched_at TIMESTAMPTZ(6) DEFAULT now(),      -- 기상청 API 수신 시각
    created_at TIMESTAMPTZ(6) DEFAULT now(),
    updated_at TIMESTAMPTZ(6) DEFAULT now()
);

-- stn_id 유니크 제약 (upsert 기준)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_weather_stations_stn_id'
    ) THEN
        ALTER TABLE review.weather_stations
            ADD CONSTRAINT uq_weather_stations_stn_id UNIQUE (stn_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_weather_stations_stn_id
    ON review.weather_stations (stn_id);


-- ──────────────────────────────────────────────────────────
-- 2. race_weather — 대회별 당일 날씨
--    CORE API /api/weather/race/{id} 가 자동 수집·저장
-- ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS review.race_weather (
    id                BIGSERIAL      PRIMARY KEY,
    race_id           BIGINT         NOT NULL,    -- review.races.id 참조
    stn_id            INTEGER,                    -- 기상청 지점코드
    temperature       NUMERIC(5, 2),              -- 기온 (°C)
    humidity          NUMERIC(5, 2),              -- 상대습도 (%)
    wind_speed        NUMERIC(5, 2),              -- 풍속 (m/s)
    wind_direction    NUMERIC(5, 1),              -- 풍향 (°)
    precipitation     NUMERIC(7, 2),              -- 일강수량 (mm)
    weather_condition VARCHAR(30),                -- 맑음 / 흐림 / 비 / 눈 등
    raw_data          JSONB,                      -- 기상청 원본 JSON 보존
    fetched_at        TIMESTAMPTZ(6),             -- API 수신 시각
    created_at        TIMESTAMPTZ(6) DEFAULT now(),
    updated_at        TIMESTAMPTZ(6) DEFAULT now()
);

-- race_id 유니크 (대회 1개당 날씨 1행, upsert 기준)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_race_weather_race_id'
    ) THEN
        ALTER TABLE review.race_weather
            ADD CONSTRAINT uq_race_weather_race_id UNIQUE (race_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_race_weather_race_id
    ON review.race_weather (race_id);


-- ──────────────────────────────────────────────────────────
-- 3. GRANT (Supabase service_role / anon 접근 허용)
-- ──────────────────────────────────────────────────────────
GRANT USAGE  ON SCHEMA review                          TO service_role, anon;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON review.weather_stations, review.race_weather    TO service_role;
GRANT SELECT
    ON review.weather_stations, review.race_weather    TO anon;
GRANT USAGE, SELECT
    ON ALL SEQUENCES IN SCHEMA review                  TO service_role;
