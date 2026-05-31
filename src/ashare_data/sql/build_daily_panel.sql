CREATE OR REPLACE TABLE daily_panel AS
WITH member_snapshot AS (
    SELECT
        d.trade_date,
        d.ts_code,
        im.index_code,
        im.con_code,
        im.in_date,
        im.out_date,
        ROW_NUMBER() OVER (
            PARTITION BY d.trade_date, d.ts_code
            ORDER BY COALESCE(im.in_date, '') DESC, im.index_code
        ) AS rn
    FROM daily AS d
    LEFT JOIN index_member_all AS im
        ON d.ts_code = im.con_code
        AND d.trade_date >= im.in_date
        AND (im.out_date IS NULL OR d.trade_date < im.out_date)
),
member_one AS (
    SELECT
        trade_date,
        ts_code,
        index_code AS industry_index_code,
        in_date AS industry_in_date,
        out_date AS industry_out_date
    FROM member_snapshot
    WHERE rn = 1
)
SELECT
    d.ts_code,
    d.trade_date,
    d.open,
    d.high,
    d.low,
    d.close,
    d.pre_close,
    d.change,
    d.pct_chg,
    d.vol,
    d.amount,
    af.adj_factor,
    db.turnover_rate,
    db.turnover_rate_f,
    db.volume_ratio,
    db.pe,
    db.pe_ttm,
    db.pb,
    db.ps,
    db.ps_ttm,
    db.dv_ratio,
    db.dv_ttm,
    db.total_share,
    db.float_share,
    db.free_share,
    db.total_mv,
    db.circ_mv,
    sl.up_limit,
    sl.down_limit,
    sd.suspend_timing,
    sd.suspend_type,
    m.industry_index_code,
    m.industry_in_date,
    m.industry_out_date
FROM daily AS d
LEFT JOIN adj_factor AS af
    ON d.ts_code = af.ts_code
    AND d.trade_date = af.trade_date
LEFT JOIN daily_basic AS db
    ON d.ts_code = db.ts_code
    AND d.trade_date = db.trade_date
LEFT JOIN stk_limit AS sl
    ON d.ts_code = sl.ts_code
    AND d.trade_date = sl.trade_date
LEFT JOIN suspend_d AS sd
    ON d.ts_code = sd.ts_code
    AND d.trade_date = sd.trade_date
LEFT JOIN member_one AS m
    ON d.ts_code = m.ts_code
    AND d.trade_date = m.trade_date;
