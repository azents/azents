# RuntimeDirectNetworkAccess

Direct customer egress within one CIDR boundary.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mode** | **str** |  | 
**allowed_cidrs** | **List[str]** |  | 
**denied_cidrs** | **List[str]** |  | 

## Example

```python
from azentspublicclient.models.runtime_direct_network_access import RuntimeDirectNetworkAccess

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeDirectNetworkAccess from a JSON string
runtime_direct_network_access_instance = RuntimeDirectNetworkAccess.from_json(json)
# print the JSON string representation of the object
print(RuntimeDirectNetworkAccess.to_json())

# convert the object into a dict
runtime_direct_network_access_dict = runtime_direct_network_access_instance.to_dict()
# create an instance of RuntimeDirectNetworkAccess from a dict
runtime_direct_network_access_from_dict = RuntimeDirectNetworkAccess.from_dict(runtime_direct_network_access_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


