# RuntimeInfrastructureProfileSpec


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**profile_kind** | **str** |  | 
**contract_family** | **str** |  | 
**schema_version** | **int** |  | 
**runner_resources** | [**DockerContainerResources**](DockerContainerResources.md) |  | 
**workspace_volume** | [**KubernetesWorkspaceVolume**](KubernetesWorkspaceVolume.md) |  | 
**network_policy** | [**RuntimeNetworkPolicyModule**](RuntimeNetworkPolicyModule.md) |  | 
**service_account_name** | **str** |  | 
**scheduling** | [**KubernetesSchedulingModule**](KubernetesSchedulingModule.md) |  | 
**dind** | [**KubernetesDinDModule**](KubernetesDinDModule.md) |  | 
**network_access** | [**RuntimeNetworkAccess**](RuntimeNetworkAccess.md) |  | 
**network_name** | **str** |  | 

## Example

```python
from azentsadminclient.models.runtime_infrastructure_profile_spec import RuntimeInfrastructureProfileSpec

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeInfrastructureProfileSpec from a JSON string
runtime_infrastructure_profile_spec_instance = RuntimeInfrastructureProfileSpec.from_json(json)
# print the JSON string representation of the object
print(RuntimeInfrastructureProfileSpec.to_json())

# convert the object into a dict
runtime_infrastructure_profile_spec_dict = runtime_infrastructure_profile_spec_instance.to_dict()
# create an instance of RuntimeInfrastructureProfileSpec from a dict
runtime_infrastructure_profile_spec_from_dict = RuntimeInfrastructureProfileSpec.from_dict(runtime_infrastructure_profile_spec_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


