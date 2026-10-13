# ReplaceRuntimeEnvironmentRequest

Complete desired list; omission deletes, stored references retain values.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**entries** | [**List[RuntimeEnvironmentEntryEdit]**](RuntimeEnvironmentEntryEdit.md) |  | 

## Example

```python
from azentspublicclient.models.replace_runtime_environment_request import ReplaceRuntimeEnvironmentRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ReplaceRuntimeEnvironmentRequest from a JSON string
replace_runtime_environment_request_instance = ReplaceRuntimeEnvironmentRequest.from_json(json)
# print the JSON string representation of the object
print(ReplaceRuntimeEnvironmentRequest.to_json())

# convert the object into a dict
replace_runtime_environment_request_dict = replace_runtime_environment_request_instance.to_dict()
# create an instance of ReplaceRuntimeEnvironmentRequest from a dict
replace_runtime_environment_request_from_dict = ReplaceRuntimeEnvironmentRequest.from_dict(replace_runtime_environment_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


