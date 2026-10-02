import sys
sys.path.insert(0, '/app')
from unittest import mock
from app.providers.azure_provider import AzureProvider

p = AzureProvider()

class FakeCtx:
    params = {"size": "Standard_B2s"}
    def log(self, msg): pass

class FakeHW:
    vm_size = "Standard_B1s"
class FakeVM:
    hardware_profile = FakeHW()

with mock.patch('azure.mgmt.compute.ComputeManagementClient') as mcc, \
     mock.patch('azure.mgmt.network.NetworkManagementClient'), \
     mock.patch('azure.mgmt.resource.ResourceManagementClient'):
    compute = mcc.return_value
    compute.virtual_machines.get.return_value = FakeVM()
    msg = p._resize(compute, 'rg1', 'vm1', FakeCtx())
    # 验证调用顺序：deallocate -> update -> start
    compute.virtual_machines.begin_deallocate.assert_called_once()
    up_args = compute.virtual_machines.begin_update.call_args
    assert up_args[0][:2] == ('rg1', 'vm1')
    assert up_args[0][2]['hardware_profile'].vm_size == 'Standard_B2s'
    compute.virtual_machines.begin_start.assert_called_once()
    print('resize OK:', msg)

    # 相同规格应拒绝
    class FakeCtx2(FakeCtx):
        params = {"size": "Standard_B1s"}
    try:
        p._resize(compute, 'rg1', 'vm1', FakeCtx2())
        print('FAIL')
    except ValueError as e:
        print('same size reject OK:', e)
print('ALL OK')
