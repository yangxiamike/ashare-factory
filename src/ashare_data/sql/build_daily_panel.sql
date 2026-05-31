WITH industry_history AS (
    SELECT
        COALESCE(CAST(con_code AS VARCHAR), CAST(ts_code AS VARCHAR)) AS ts_code,
        CAST(con_name AS VARCHAR) AS con_name,
        CAST(l1_code AS VARCHAR) AS l1_code,
        CAST(l1_name AS VARCHAR) AS l1_name,
        CAST(l2_code AS VARCHAR) AS l2_code,
        CAST(l2_name AS VARCHAR) AS l2_name,
        CAST(l3_code AS VARCHAR) AS l3_code,
        CAST(l3_name AS VARCHAR) AS l3_name,
        CAST(in_date AS VARCHAR) AS in_date,
        CAST(out_date AS VARCHAR) AS out_date,
        CAST(is_new AS VARCHAR) AS is_new
    FROM index_member_all
),
suspend_flags AS (
    SELECT
        ts_code,
        trade_date,
        TRUE AS is_suspended,
        string_agg(DISTINCT suspend_type, ',') AS suspend_type,
        string_agg(DISTINCT suspend_timing, ',') AS suspend_timing
    FROM suspend_d
    GROUP BY ts_code, trade_date
)
SELECT
    d.trade_date,
    d.ts_code,
    sb.name,
    sb.market,
    sb.area,
    sb.industry AS stock_basic_industry,
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
    COALESCE(sf.is_suspended, FALSE) AS is_suspended,
    sf.suspend_type,
    sf.suspend_timing,
    ih.con_name AS sw_member_name,
    ih.l1_code AS sw_l1_code,
    ih.l1_name AS sw_l1_name,
    ih.l2_code AS sw_l2_code,
    ih.l2_name AS sw_l2_name,
    ih.l3_code AS sw_l3_code,
    ih.l3_name AS sw_l3_name,
    ih.in_date AS sw_in_date,
    ih.out_date AS sw_out_date,
    ih.is_new AS sw_is_new
FROM daily d
LEFT JOIN stock_basic sb
    ON d.ts_code = sb.ts_code
LEFT JOIN adj_factor af
    ON d.trade_date = af.trade_date
    AND d.ts_code = af.ts_code
LEFT JOIN daily_basic db
    ON d.trade_date = db.trade_date
    AND d.ts_code = db.ts_code
LEFT JOIN stk_limit sl
    ON d.trade_date = sl.trade_date
    AND d.ts_code = sl.ts_code
LEFT JOIN suspend_flags sf
    ON d.trade_date = sf.trade_date
    AND d.ts_code = sf.ts_code
LEFT JOIN industry_history ih
    ON d.ts_code = ih.ts_code
    AND d.trade_date >= ih.in_date
    AND (ih.out_date IS NULL OR ih.out_date = '' OR d.trade_date < ih.out_date)
WHERE (? IS NULL OR d.trade_date >= ?)
  AND (? IS NULL OR d.trade_date <= ?)
QUALIFY row_number() OVER (
    PARTITION BY d.trade_date, d.ts_code
    ORDER BY
        CASE WHEN ih.is_new = 'Y' THEN 0 ELSE 1 END,
        ih.in_date DESC NULLS LAST,
        ih.out_date DESC NULLS LAST
) = 1
