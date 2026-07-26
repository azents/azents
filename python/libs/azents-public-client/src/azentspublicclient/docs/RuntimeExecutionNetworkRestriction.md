# RuntimeExecutionNetworkRestriction

Optional lower-layer egress narrowing.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mode** | [**RuntimeExecutionNetworkMode**](RuntimeExecutionNetworkMode.md) |  | 
**allowed_destinations** | **List[str]** |  | 
**denied_destinations** | **List[str]** |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_network_restriction import RuntimeExecutionNetworkRestriction

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionNetworkRestriction from a JSON string
runtime_execution_network_restriction_instance = RuntimeExecutionNetworkRestriction.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionNetworkRestriction.to_json())

# convert the object into a dict
runtime_execution_network_restriction_dict = runtime_execution_network_restriction_instance.to_dict()
# create an instance of RuntimeExecutionNetworkRestriction from a dict
runtime_execution_network_restriction_from_dict = RuntimeExecutionNetworkRestriction.from_dict(runtime_execution_network_restriction_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


