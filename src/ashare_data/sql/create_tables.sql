CREATE TABLE IF NOT EXISTS trade_cal (
    exchange VARCHAR,
    cal_date VARCHAR,
    is_open VARCHAR,
    pretrade_date VARCHAR
);

CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code VARCHAR,
    symbol VARCHAR,
    name VARCHAR,
    area VARCHAR,
    industry VARCHAR,
    market VARCHAR,
    list_date VARCHAR,
    act_name VARCHAR,
    act_ent_type VARCHAR
);

CREATE TABLE IF NOT EXISTS daily (
    ts_code VARCHAR,
    trade_date VARCHAR,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    pre_close DOUBLE,
    change DOUBLE,
    pct_chg DOUBLE,
    vol DOUBLE,
    amount DOUBLE
);

CREATE TABLE IF NOT EXISTS adj_factor (ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE);

CREATE TABLE IF NOT EXISTS daily_basic (
    ts_code VARCHAR,
    trade_date VARCHAR,
    close DOUBLE,
    turnover_rate DOUBLE,
    turnover_rate_f DOUBLE,
    volume_ratio DOUBLE,
    pe DOUBLE,
    pe_ttm DOUBLE,
    pb DOUBLE,
    ps DOUBLE,
    ps_ttm DOUBLE,
    dv_ratio DOUBLE,
    dv_ttm DOUBLE,
    total_share DOUBLE,
    float_share DOUBLE,
    free_share DOUBLE,
    total_mv DOUBLE,
    circ_mv DOUBLE
);

CREATE TABLE IF NOT EXISTS suspend_d (
    ts_code VARCHAR,
    trade_date VARCHAR,
    suspend_type VARCHAR,
    suspend_timing VARCHAR
);

CREATE TABLE IF NOT EXISTS stk_limit (
    ts_code VARCHAR,
    trade_date VARCHAR,
    up_limit DOUBLE,
    down_limit DOUBLE
);

CREATE TABLE IF NOT EXISTS index_classify (
    index_code VARCHAR,
    industry_name VARCHAR,
    level VARCHAR,
    industry_code VARCHAR,
    src VARCHAR
);

CREATE TABLE IF NOT EXISTS index_member_all (
    l1_code VARCHAR,
    l1_name VARCHAR,
    l2_code VARCHAR,
    l2_name VARCHAR,
    l3_code VARCHAR,
    l3_name VARCHAR,
    ts_code VARCHAR,
    con_code VARCHAR,
    con_name VARCHAR,
    in_date VARCHAR,
    out_date VARCHAR,
    is_new VARCHAR
);

CREATE TABLE IF NOT EXISTS daily_panel AS SELECT * FROM daily WHERE 1 = 0;
