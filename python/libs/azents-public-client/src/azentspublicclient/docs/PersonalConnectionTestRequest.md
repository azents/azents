# PersonalConnectionTestRequest

Common test fields with saved IDs restricted to the current owner.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**toolkit_type** | **str** | Toolkit type, such as mcp or github | [optional] [default to 'mcp']
**config** | **object** |  | 
**credentials** | **object** |  | [optional] 
**toolkit_config_id** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.personal_connection_test_request import PersonalConnectionTestRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalConnectionTestRequest from a JSON string
personal_connection_test_request_instance = PersonalConnectionTestRequest.from_json(json)
# print the JSON string representation of the object
print(PersonalConnectionTestRequest.to_json())

# convert the object into a dict
personal_connection_test_request_dict = personal_connection_test_request_instance.to_dict()
# create an instance of PersonalConnectionTestRequest from a dict
personal_connection_test_request_from_dict = PersonalConnectionTestRequest.from_dict(personal_connection_test_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


