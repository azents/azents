# PersonalToolkitAccessResponse

Committed policy snapshot from the single personal connection authority.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**toolkit_id** | **str** |  | 
**mode** | [**PersonalToolkitAccessMode**](PersonalToolkitAccessMode.md) |  | 
**selected_agent_ids** | **List[str]** |  | 

## Example

```python
from azentspublicclient.models.personal_toolkit_access_response import PersonalToolkitAccessResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalToolkitAccessResponse from a JSON string
personal_toolkit_access_response_instance = PersonalToolkitAccessResponse.from_json(json)
# print the JSON string representation of the object
print(PersonalToolkitAccessResponse.to_json())

# convert the object into a dict
personal_toolkit_access_response_dict = personal_toolkit_access_response_instance.to_dict()
# create an instance of PersonalToolkitAccessResponse from a dict
personal_toolkit_access_response_from_dict = PersonalToolkitAccessResponse.from_dict(personal_toolkit_access_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


