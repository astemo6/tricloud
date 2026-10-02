import sys
sys.path.insert(0, '/app')
from app import db
from app.providers import get_provider
from unittest import mock

acc = db.account_get(3)
p = get_provider('aws')

# 1. 真实读取套餐（只读）
plans = p.get_cf_plans(acc['creds'])
print('plans:', plans)
assert plans == {}, plans  # 用户当前全是 paygo

# 2. list 包含 plan 字段
ds = p.list_cloudfront(acc['creds'])
assert all('plan' in d for d in ds), 'missing plan field'
assert all(d['plan'] == 'paygo' for d in ds)
print('list plan field OK:', [(d['id'], d['plan']) for d in ds])

# 3. mock 验证 set_cf_plan 逻辑
with mock.patch('boto3.client') as mc:
    ppm = mc.return_value
    # 订阅到 PRO
    ppm.create_subscription.return_value = {'subscription': {'status': 'ACTIVE'}}
    msg = p.set_cf_plan(acc['creds'], 'E123', '123456789', 'PRO')
    args, kw = ppm.create_subscription.call_args
    assert kw['planFamily'] == 'CloudFront'
    assert kw['planTier'] == 'PRO'
    assert kw['resourceArns'] == ['arn:aws:cloudfront::123456789:distribution/E123']
    assert kw['approvalMode'] == 'IMMEDIATE'
    print('subscribe OK:', msg[:50])

    # 切回 paygo
    ppm.get_paginator.return_value.paginate.return_value = [{
        'subscriptionSummaries': [{
            'planFamily': 'CloudFront', 'arn': 'sub-arn',
            'resourceArns': ['arn:aws:cloudfront::123456789:distribution/E123'],
        }]
    }]
    msg = p.set_cf_plan(acc['creds'], 'E123', '123456789', 'paygo')
    dk, dkw = ppm.disassociate_resources_from_subscription.call_args
    assert dkw['arn'] == 'sub-arn'
    print('unsubscribe OK:', msg[:40])

    # 非法 tier
    try:
        p.set_cf_plan(acc['creds'], 'E123', '123', 'GOLD')
        print('FAIL')
    except ValueError as e:
        print('invalid tier OK:', e)
print('ALL OK')
