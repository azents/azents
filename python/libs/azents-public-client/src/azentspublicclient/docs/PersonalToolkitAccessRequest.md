# PersonalToolkitAccessRequest

Explicit expected mode and membership deltas, independent of search filters.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_mode** | [**PersonalToolkitAccessMode**](PersonalToolkitAccessMode.md) |  | 
**mode** | [**PersonalToolkitAccessMode**](PersonalToolkitAccessMode.md) |  | 
**allow_agent_ids** | **List[str]** |  | 
**restrict_agent_ids** | **List[str]** |  | 

## Example

```python
from azentspublicclient.models.personal_toolkit_access_request import PersonalToolkitAccessRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalToolkitAccessRequest from a JSON string
personal_toolkit_access_request_instance = PersonalToolkitAccessRequest.from_json(json)
# print the JSON string representation of the object
print(PersonalToolkitAccessRequest.to_json())

# convert the object into a dict
personal_toolkit_access_request_dict = personal_toolkit_access_request_instance.to_dict()
# create an instance of PersonalToolkitAccessRequest from a dict
personal_toolkit_access_request_from_dict = PersonalToolkitAccessRequest.from_dict(personal_toolkit_access_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


