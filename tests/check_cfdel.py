import sys
sys.path.insert(0, '/app')
from app import db
from app.providers import get_provider
from unittest import mock

acc = db.account_get(3)
p = get_provider('aws')

with mock.patch('boto3.client') as mc:
    cf = mc.return_value

    # 1. 启用中的分发 -> 拒绝
    cf.get_distribution_config.return_value = {
        'ETag': 'E1', 'DistributionConfig': {'Enabled': True}}
    try:
        p.delete_distribution(acc['creds'], 'E123')
        print('FAIL: should reject enabled')
    except ValueError as e:
        assert '停用' in str(e)
        print('enabled reject OK')

    # 2. 已停用但部署中 -> 拒绝
    cf.get_distribution_config.return_value = {
        'ETag': 'E1', 'DistributionConfig': {'Enabled': False}}
    cf.get_distribution.return_value = {'Distribution': {'Status': 'InProgress'}}
    try:
        p.delete_distribution(acc['creds'], 'E123')
        print('FAIL: should reject inprogress')
    except ValueError as e:
        assert 'InProgress' in str(e)
        print('inprogress reject OK')

    # 3. 已停用且已部署 -> 删除
    cf.get_distribution.return_value = {'Distribution': {'Status': 'Deployed'}}
    msg = p.delete_distribution(acc['creds'], 'E123')
    dk, dkw = cf.delete_distribution.call_args
    assert dkw['Id'] == 'E123' and dkw['IfMatch'] == 'E1'
    print('delete OK:', msg)
print('ALL OK')
