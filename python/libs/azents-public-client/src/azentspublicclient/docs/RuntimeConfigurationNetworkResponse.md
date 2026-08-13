# RuntimeConfigurationNetworkResponse

Bounded effective Runtime network presentation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mode** | [**RuntimeNetworkMode**](RuntimeNetworkMode.md) |  | 
**domain_mode** | **str** |  | 
**protocol_summary** | **str** |  | 
**https_inspection** | **bool** |  | 
**enforcement_status** | [**RuntimeConfigurationStatus**](RuntimeConfigurationStatus.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_configuration_network_response import RuntimeConfigurationNetworkResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeConfigurationNetworkResponse from a JSON string
runtime_configuration_network_response_instance = RuntimeConfigurationNetworkResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeConfigurationNetworkResponse.to_json())

# convert the object into a dict
runtime_configuration_network_response_dict = runtime_configuration_network_response_instance.to_dict()
# create an instance of RuntimeConfigurationNetworkResponse from a dict
runtime_configuration_network_response_from_dict = RuntimeConfigurationNetworkResponse.from_dict(runtime_configuration_network_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


