-- Portal settings: drop the two seeded settings that controlled nothing.
-- high_impact_rule only held a description (the rule lives in code: regtrack/api/portal.py IMPACT_RULE);
-- obligations always appear in the Compliance Matrix, so auto_compliance_task had no effect.
DELETE FROM app_setting WHERE key IN ('high_impact_rule', 'auto_compliance_task');
