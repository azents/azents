# RuntimeNetworkProjection

Safe server-authored Runtime network authority projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mode** | [**RuntimeNetworkMode**](RuntimeNetworkMode.md) |  | 
**allowed_cidrs** | **List[str]** |  | 
**denied_cidrs** | **List[str]** |  | 
**domain_mode** | [**RuntimeProxyDomainMode**](RuntimeProxyDomainMode.md) |  | 
**allowed_domains** | **List[str]** |  | 
**denied_domains** | **List[str]** |  | 

## Example

```python
from azentspublicclient.models.runtime_network_projection import RuntimeNetworkProjection

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeNetworkProjection from a JSON string
runtime_network_projection_instance = RuntimeNetworkProjection.from_json(json)
# print the JSON string representation of the object
print(RuntimeNetworkProjection.to_json())

# convert the object into a dict
runtime_network_projection_dict = runtime_network_projection_instance.to_dict()
# create an instance of RuntimeNetworkProjection from a dict
runtime_network_projection_from_dict = RuntimeNetworkProjection.from_dict(runtime_network_projection_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


