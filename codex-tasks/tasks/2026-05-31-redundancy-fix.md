# 对你的要求

下面是两件事，按顺序做：先改代码，再更新 AGENTS.md。

---

## 第一步：修代码冗余

以下 5 个问题都已有明确目标代码，直接改，不要问我确认。改完做一个 commit。

### 1. 删掉死代码 `_concat_daily`

`src/ashare_data/ingest.py` 的 `_concat_daily` 函数已被 `_persist_recent_daily_endpoint` 替代，没有调用方了。删掉。

### 2. 去掉双重 partition 检查

`src/ashare_data/ingest.py` 里 `ingest_history` 的 skip 逻辑：

```python
if not force and has_successful_ingest(settings, endpoint, trade_date):
    if has_raw_daily_partition(settings, endpoint, trade_date):
```

`has_successful_ingest` 内部已经检查了 raw_path 文件是否存在，外层的 `has_raw_daily_partition` 查的是同一个路径，完全重复。把内层 if 去掉，只保留 `has_successful_ingest`。

### 3. 合并 `EXPECTED_COLUMNS` 和 `TEXT_COLUMNS`

`src/ashare_data/storage.py` 里这两个 dict 定义相同的 10 个表，`TEXT_COLUMNS` 是 `EXPECTED_COLUMNS` 的子集。合并成一个结构：从 `EXPECTED_COLUMNS` 推导出 `TEXT_COLUMNS`，或者只保留一份，另一份用代码自动生成。

注意：`TEXT_COLUMNS` 还用在 `_migrate_warehouse_schema` 里做 ALTER TABLE。确保迁移逻辑不受影响。

### 4. 简化 DQ 的 `_resolve_report_dir`

`src/ashare_data/dq.py` 的 `_resolve_report_dir` 有三层 fallback，但 CLI 调用时永远传 pydantic Settings 对象（有 `report_dir` 且是绝对路径），第二、三层永远不会触发。同时 `build_settings_for_path` 创建的 `SimpleNamespace` 路径在 CLI 里从未使用。

把 `_resolve_report_dir` 简化为只取 `settings.report_dir`。如果这样做会让 `build_settings_for_path` 成为死代码，一并删掉。

### 5. 去掉 `record_ingest_status` 的 CASE WHEN NULL

`src/ashare_data/storage.py` 里 `record_ingest_status` 的 SQL：

```sql
CASE WHEN ? IS NULL THEN current_timestamp ELSE CAST(? AS TIMESTAMP) END
```

查所有调用方——`started_at` 和 `finished_at` 从不传 None。把 CASE WHEN 换成直接 `CAST(? AS TIMESTAMP)`，并把这俩参数的类型 hint 从 `str | None` 改为 `str`。

---

## 第二步：更新 AGENTS.md

在现有 AGENTS.md 的 "工作要求" 部分后面追加以下内容。不要改动已有内容。

```markdown
## 代码结构规范

### 防御性编码禁令

- 不在上下游重复校验同一条件。只在 system boundary（用户输入、外部 API）做验证，不信任调用方时用 assert 而非 if-guard。
- 写函数前先 grep 所有调用方，确认参数的实际取值范围，不为不存在的场景写 fallback。
- 函数签名不要为了"以后可能有别的调用方"而放宽类型（如 `str | None`），只反映当前实际调用链。
- 重构时新代码上线后，旧代码必须删除。不许留尸体。

### Schema / 常量定义

- 同一份信息（表名、字段列表、列类型）只在一个地方定义，其他模块引用。不接受维护两套几乎一样的 dict。

### 代码审查自检

每次写代码后，自问：
- 这个检查是不是上游已经做过了？
- 这个 null guard 是不是真会触发？
- 这个 fallback 路径是不是真实有调用方会走？
- 有没有刚被我替换掉但忘记删的旧函数？

如果任一答案是"是"，先改掉再提交。
```

---

## 第三步：commit

把代码改动的文件和 AGENTS.md 放在一个 commit 里，message：

```
refactor: remove defensive redundancy and dead code
```
