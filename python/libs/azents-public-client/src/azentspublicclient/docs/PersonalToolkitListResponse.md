# PersonalToolkitListResponse

Personal connections available to this exact account's management UI.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[PersonalToolkitResponse]**](PersonalToolkitResponse.md) |  | 

## Example

```python
from azentspublicclient.models.personal_toolkit_list_response import PersonalToolkitListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalToolkitListResponse from a JSON string
personal_toolkit_list_response_instance = PersonalToolkitListResponse.from_json(json)
# print the JSON string representation of the object
print(PersonalToolkitListResponse.to_json())

# convert the object into a dict
personal_toolkit_list_response_dict = personal_toolkit_list_response_instance.to_dict()
# create an instance of PersonalToolkitListResponse from a dict
personal_toolkit_list_response_from_dict = PersonalToolkitListResponse.from_dict(personal_toolkit_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


