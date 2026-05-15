-- =============================================
-- 스키마 분리 구조
-- Supabase 대시보드 > SQL Editor 에서 실행
-- =============================================

-- 스키마 생성
CREATE SCHEMA IF NOT EXISTS review;
CREATE SCHEMA IF NOT EXISTS crew;

-- =============================================
-- public 스키마 : 공통 (회원 / 조직)
-- =============================================

CREATE TABLE IF NOT EXISTS public.crews (
    id         BIGSERIAL PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.branches (
    id         BIGSERIAL PRIMARY KEY,
    crew_id    BIGINT REFERENCES public.crews(id) ON DELETE CASCADE,
    name       VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.groups (
    id         BIGSERIAL PRIMARY KEY,
    branch_id  BIGINT REFERENCES public.branches(id) ON DELETE CASCADE,
    name       VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.users (
    id            BIGSERIAL PRIMARY KEY,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password      VARCHAR(255) NOT NULL,
    name          VARCHAR(100),
    nickname      VARCHAR(100),
    crew_id       BIGINT REFERENCES public.crews(id),
    branch_id     BIGINT REFERENCES public.branches(id),
    group_id      BIGINT REFERENCES public.groups(id),
    role          VARCHAR(20) NOT NULL DEFAULT 'member'
                  CHECK (role IN ('super_admin','crew_admin','group_admin','member')),
    is_beta       BOOLEAN DEFAULT FALSE,
    invite_code   VARCHAR(50),
    last_login_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- updated_at 자동 갱신 함수
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_updated_at
    BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- =============================================
-- review 스키마 : 대회 리뷰 전용
-- =============================================

CREATE TABLE IF NOT EXISTS review.races (
    id           BIGSERIAL PRIMARY KEY,
    name         VARCHAR(200) NOT NULL,
    race_date    DATE NOT NULL,
    location     VARCHAR(200),
    city         VARCHAR(100),
    organizer    VARCHAR(200),
    distances    TEXT[],         -- 예: ARRAY['5K','10K','하프','풀']
    entry_fee    INTEGER,
    website_url  VARCHAR(500),
    is_active    BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS review.reviews (
    id           BIGSERIAL PRIMARY KEY,
    race_id      BIGINT REFERENCES review.races(id) ON DELETE CASCADE,
    user_id      BIGINT REFERENCES public.users(id) ON DELETE CASCADE,
    distance     VARCHAR(20),
    rating       SMALLINT CHECK (rating BETWEEN 1 AND 5),
    content      TEXT,
    ai_summary   TEXT,          -- Claude API 요약
    sentiment    VARCHAR(20),   -- positive / neutral / negative
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS review.race_weather (
    id           BIGSERIAL PRIMARY KEY,
    race_id      BIGINT REFERENCES review.races(id) ON DELETE CASCADE,
    temperature  NUMERIC(4,1),
    humidity     SMALLINT,
    wind_speed   NUMERIC(4,1),
    condition    VARCHAR(50),   -- 맑음 / 흐림 / 비 등
    fetched_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER races_updated_at
    BEFORE UPDATE ON review.races
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER reviews_updated_at
    BEFORE UPDATE ON review.reviews
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- =============================================
-- crew 스키마 : 러닝 크루 전용
-- =============================================

CREATE TABLE IF NOT EXISTS crew.running_logs (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT REFERENCES public.users(id) ON DELETE CASCADE,
    log_date       DATE NOT NULL,
    distance_km    NUMERIC(6,2),
    avg_pace       VARCHAR(10),
    best_pace      VARCHAR(10),
    duration_sec   INTEGER,
    calories       INTEGER,
    avg_heart_rate INTEGER,
    is_indoor      BOOLEAN DEFAULT FALSE,
    altitude_m     NUMERIC(7,1),
    image_url      VARCHAR(500),
    raw_parsed     JSONB,        -- Claude Vision 파싱 원본
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crew.events (
    id          BIGSERIAL PRIMARY KEY,
    group_id    BIGINT REFERENCES public.groups(id),
    name        VARCHAR(200) NOT NULL,
    start_date  DATE,
    end_date    DATE,
    base_score  INTEGER DEFAULT 0,
    memo        TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crew.event_scores (
    id         BIGSERIAL PRIMARY KEY,
    event_id   BIGINT REFERENCES crew.events(id) ON DELETE CASCADE,
    user_id    BIGINT REFERENCES public.users(id) ON DELETE CASCADE,
    score      INTEGER NOT NULL DEFAULT 0,
    memo       TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crew.user_goals (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT REFERENCES public.users(id) ON DELETE CASCADE,
    target_km    NUMERIC(7,2) NOT NULL,
    start_date   DATE NOT NULL,
    end_date     DATE NOT NULL,
    is_achieved  BOOLEAN DEFAULT FALSE,
    reward_score INTEGER DEFAULT 0,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================
-- PostgREST 에 review / crew 스키마 접근 권한 부여
-- =============================================
GRANT USAGE ON SCHEMA review TO anon, authenticated, service_role;
GRANT USAGE ON SCHEMA crew   TO anon, authenticated, service_role;

GRANT ALL ON ALL TABLES    IN SCHEMA review TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA review TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES    IN SCHEMA crew   TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA crew   TO anon, authenticated, service_role;
