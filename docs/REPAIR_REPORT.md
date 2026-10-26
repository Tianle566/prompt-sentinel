# Prompt Sentinel 审核问题修复报告

12 项均完成；每项都有旧实现失败、修复后通过的回归测试。下面列出逐项文件、完整新增测试名和红绿证据。

最终命令（项目虚拟环境）：

```bash
python -m pytest -q -m "not integration"
```

结果：**247 passed, 1 deselected, 1 warning in 15.24s**。唯一排除项为官方数据集 integration 测试；前端生产构建通过。warning 是依赖库已有的 Starlette/httpx 弃用提示。

`backend/config.yaml` 与修复前逐字节一致，SHA-256：`cc5cdcda3e4f823508d7db301a28939b58a2382d7d2a81322f2388ecaed4a081`。没有重建历史数据集或模型实验，旧 v1 指标不代表新 v2 模板。

第 12 项采用删除请求字段的方案：EvalBody 及实际前端请求体均不再包含 dataset。界面快捷选择仍同步实验类型，数据使用范围由实验类型确定。

红绿证据：金丝雀 5 failed → 7 passed；规则/模板 14 failed → 29 passed；配置/依赖/标记 92 failed → 116 passed（含相关既有测试，1 integration deselected）；补充完整配置中非法 CORS 的 3 failed → 3 passed；文档 3 failed → 3 passed；接口 21 failed → 22 passed。旧实现中有正例已通过，故失败数不必等于最终用例总数。

## 1. 金丝雀变体检测与遮蔽

修改文件：

- [backend/app/defense/canary.py](../backend/app/defense/canary.py)
- [backend/app/defense/output_check.py](../backend/app/defense/output_check.py)
- [backend/app/services/evaluation.py](../backend/app/services/evaluation.py)
- [backend/tests/test_canary_regressions.py](../backend/tests/test_canary_regressions.py)

新增回归测试：

- `test_canary_variants_are_detected_redacted_and_judged`（[test_canary_regressions.py](../backend/tests/test_canary_regressions.py:16)）
- `test_canary_normalization_is_case_insensitive_and_removes_mixed_separators`（[test_canary_regressions.py](../backend/tests/test_canary_regressions.py:32)）
- `test_canary_redaction_preserves_unrelated_content_and_arbitrary_exact_secrets`（[test_canary_regressions.py](../backend/tests/test_canary_regressions.py:39)）
- `test_canary_disabled_layer_still_reports_leak_for_raw_oracle`（[test_canary_regressions.py](../backend/tests/test_canary_regressions.py:49)）
- `test_canary_oracle_prefers_recorded_boolean_over_public_text`（[test_canary_regressions.py](../backend/tests/test_canary_regressions.py:57)）

红绿证据：`.runtime/repairs/01-red.log`, `.runtime/repairs/01-green.log`。

## 2. 评测不持全局锁，保护接口获取锁超时返回503

修改文件：

- [backend/app/api/routes.py](../backend/app/api/routes.py)
- [backend/tests/test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py)

新增回归测试：

- `test_detect_returns_503_within_five_second_lock_deadline`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:34)）
- `test_protected_routes_use_bounded_acquisition_during_evaluation`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:54)）
- `test_evaluation_releases_global_lock_and_clears_running_state`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:81)）

红绿证据：`.runtime/repairs/02-07-08-10-12-red.log`, `.runtime/repairs/02-07-08-10-12-green.log`。

## 3. 规则解码校验与合法ZWJ/ZWNJ放行

修改文件：

- [backend/rules.yaml](../backend/rules.yaml)
- [backend/app/detectors/rules.py](../backend/app/detectors/rules.py)
- [backend/tests/test_rule_template_regressions.py](../backend/tests/test_rule_template_regressions.py)
- [backend/tests/test_core_detection.py](../backend/tests/test_core_detection.py)

新增回归测试：

- `test_legitimate_zwj_and_zwnj_do_not_trigger_zero_width`（[test_rule_template_regressions.py](../backend/tests/test_rule_template_regressions.py:20)）
- `test_other_zero_width_and_bidi_controls_remain_detected`（[test_rule_template_regressions.py](../backend/tests/test_rule_template_regressions.py:25)）
- `test_urls_hashes_and_unreadable_encoded_bytes_are_not_encoding_hits`（[test_rule_template_regressions.py](../backend/tests/test_rule_template_regressions.py:38)）
- `test_base64_readable_payload_at_lower_threshold_is_detected`（[test_rule_template_regressions.py](../backend/tests/test_rule_template_regressions.py:42)）
- `test_encoding_readability_requires_eighty_percent_printable_utf8`（[test_rule_template_regressions.py](../backend/tests/test_rule_template_regressions.py:50)）
- `test_every_local_encoded_template_hits_its_encoding_rule`（[test_rule_template_regressions.py](../backend/tests/test_rule_template_regressions.py:58)）

红绿证据：`.runtime/repairs/03-04-red.log`, `.runtime/repairs/03-04-green.log`。

## 4. 本地模板v2：encoded/indirect每语言五种结构

修改文件：

- [scripts/build_dataset.py](../scripts/build_dataset.py)
- [README.md](../README.md)
- [backend/tests/test_rule_template_regressions.py](../backend/tests/test_rule_template_regressions.py)
- [backend/tests/test_deployment_contract.py](../backend/tests/test_deployment_contract.py)

新增回归测试：

- `test_local_templates_have_five_structures_per_language_and_are_reproducible`（[test_rule_template_regressions.py](../backend/tests/test_rule_template_regressions.py:70)）
- `test_template_v2_provenance_is_recorded_in_manifest_and_both_corpora`（[test_rule_template_regressions.py](../backend/tests/test_rule_template_regressions.py:83)）
- `test_readme_identifies_local_encoded_indirect_data_limitations`（[test_deployment_contract.py](../backend/tests/test_deployment_contract.py:14)）

红绿证据：`.runtime/repairs/03-04-red.log`, `.runtime/repairs/03-04-green.log`, `.runtime/repairs/04-05-11-docs-red.log`, `.runtime/repairs/04-05-11-docs-green.log`。

## 5. 严格配置类型/范围与OpenAI密钥接收地址说明

修改文件：

- [backend/app/core/config.py](../backend/app/core/config.py)
- [backend/app/api/routes.py](../backend/app/api/routes.py)
- [README.md](../README.md)
- [backend/tests/test_config_regressions.py](../backend/tests/test_config_regressions.py)
- [backend/tests/test_deployment_contract.py](../backend/tests/test_deployment_contract.py)

新增回归测试：

- `test_new_config_fields_reject_invalid_values`（[test_config_regressions.py](../backend/tests/test_config_regressions.py:46)）
- `test_new_integer_config_fields_accept_inclusive_bounds`（[test_config_regressions.py](../backend/tests/test_config_regressions.py:53)）
- `test_cors_origins_requires_string_list`（[test_config_regressions.py](../backend/tests/test_config_regressions.py:60)）
- `test_cors_origins_accepts_string_lists`（[test_config_regressions.py](../backend/tests/test_config_regressions.py:68)）
- `test_config_put_rejects_invalid_values_without_rewriting_file`（[test_config_regressions.py](../backend/tests/test_config_regressions.py:103)）
- `test_config_put_preserves_cors_origins_readonly_scope`（[test_config_regressions.py](../backend/tests/test_config_regressions.py:112)）
- `test_config_put_rejects_invalid_cors_in_full_policy_without_writes`（[test_config_regressions.py](../backend/tests/test_config_regressions.py:121)）
- `test_readme_discloses_openai_base_url_receives_api_key`（[test_deployment_contract.py](../backend/tests/test_deployment_contract.py:24)）

红绿证据：`.runtime/repairs/05-06-09-red.log`, `.runtime/repairs/05-06-09-green.log`, `.runtime/repairs/04-05-11-docs-red.log`, `.runtime/repairs/04-05-11-docs-green.log`, `.runtime/repairs/05-cors-full-policy-red.log`, `.runtime/repairs/05-cors-full-policy-green.log`。

## 6. Ollama下限0.6.3

修改文件：

- [backend/requirements.txt](../backend/requirements.txt)
- [backend/tests/test_config_regressions.py](../backend/tests/test_config_regressions.py)

新增回归测试：

- `test_ollama_requirement_excludes_versions_before_0_6_3`（[test_config_regressions.py](../backend/tests/test_config_regressions.py:131)）

红绿证据：`.runtime/repairs/05-06-09-red.log`, `.runtime/repairs/05-06-09-green.log`。

## 7. 登录假哈希、分用户名限流、鉴权改密并移除初始凭据

修改文件：

- [backend/app/api/routes.py](../backend/app/api/routes.py)
- [README.md](../README.md)
- [backend/tests/test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py)

新增回归测试：

- `test_unknown_login_always_checks_precomputed_bcrypt_hash`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:108)）
- `test_login_rate_limit_isolated_by_username`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:122)）
- `test_password_change_invalidates_old_password_and_removes_bootstrap_entry`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:132)）
- `test_password_change_rejects_invalid_utf8_byte_lengths`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:150)）
- `test_password_change_requires_login_and_correct_old_password`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:160)）

红绿证据：`.runtime/repairs/02-07-08-10-12-red.log`, `.runtime/repairs/02-07-08-10-12-green.log`。

## 8. 无防护chat限制本机目标

修改文件：

- [backend/app/api/routes.py](../backend/app/api/routes.py)
- [backend/tests/test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py)

新增回归测试：

- `test_unprotected_chat_rejects_remote_target_before_generation`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:172)）

红绿证据：`.runtime/repairs/02-07-08-10-12-red.log`, `.runtime/repairs/02-07-08-10-12-green.log`。

## 9. 官方数据测试标记integration

修改文件：

- [backend/tests/test_evaluation.py](../backend/tests/test_evaluation.py)
- [backend/tests/test_config_regressions.py](../backend/tests/test_config_regressions.py)

新增回归测试：

- `test_official_dataset_contract_is_integration_only`（[test_config_regressions.py](../backend/tests/test_config_regressions.py:140)）

红绿证据：`.runtime/repairs/05-06-09-red.log`, `.runtime/repairs/05-06-09-green.log`。

## 10. 统计SQL聚合，分层延迟最多读取最近1000条

修改文件：

- [backend/app/api/routes.py](../backend/app/api/routes.py)
- [backend/tests/test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py)

新增回归测试：

- `test_stats_aggregates_history_but_bounds_latency_to_latest_1000`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:181)）

红绿证据：`.runtime/repairs/02-07-08-10-12-red.log`, `.runtime/repairs/02-07-08-10-12-green.log`。

## 11. 明确单worker部署约束

修改文件：

- [README.md](../README.md)
- [backend/tests/test_deployment_contract.py](../backend/tests/test_deployment_contract.py)

新增回归测试：

- `test_readme_requires_single_worker_for_in_memory_state`（[test_deployment_contract.py](../backend/tests/test_deployment_contract.py:35)）

红绿证据：`.runtime/repairs/04-05-11-docs-red.log`, `.runtime/repairs/04-05-11-docs-green.log`。

## 12. 删除EvalBody.dataset及前端/验收脚本传参

修改文件：

- [backend/app/api/routes.py](../backend/app/api/routes.py)
- [frontend/src/pages/Evaluation.vue](../frontend/src/pages/Evaluation.vue)
- [scripts/verify_system.py](../scripts/verify_system.py)
- [backend/tests/test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py)

新增回归测试：

- `test_eval_request_schema_has_no_unused_dataset_selector`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:210)）
- `test_frontend_evaluation_request_does_not_send_dataset`（[test_api_audit_regressions.py](../backend/tests/test_api_audit_regressions.py:214)）

红绿证据：`.runtime/repairs/02-07-08-10-12-red.log`, `.runtime/repairs/02-07-08-10-12-green.log`。

第 3 项同时把原有测试中的不可读 `A*100`、`0x+ab*20` 两个伪编码正例改为真实可读 UTF-8 编码；没有放松断言来掩盖误报。

第 5 项额外覆盖完整配置同时含非法 CORS 和合法 fusion 修改的情况：整个请求返回422，不再忽略非法只读值后保存其他字段；CORS 依然不能通过此策略接口修改。

统计测试包含1005条本人日志及另一用户日志，验证全历史计数、日期/类型分组、访问隔离、最近1000条延迟、避免全量实例化日志对象。锁测试实际持锁并检查五秒期限，另覆盖chat/detect/document/attack及评测成功/异常清理。

只读本机烟测确认改密接口未登录返回401、EvalBody schema无dataset、SQL统计返回200；没有更改真实用户密码。详细运行日志在 `.runtime/repairs/`。
