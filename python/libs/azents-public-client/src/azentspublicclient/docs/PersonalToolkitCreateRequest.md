# PersonalToolkitCreateRequest

Common Provider options with owner identity derived only from authentication.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**toolkit_type** | **str** | Tool type | 
**slug** | **str** | Optional base alias. Explicit values are normalized to lowercase ASCII letters, numbers, and underscores. | [optional] 
**name** | **str** | Display name | [optional] 
**description** | **str** |  | [optional] 
**config** | **object** | Tool settings | 
**prompt** | **str** |  | [optional] 
**credentials** | **object** |  | [optional] 
**enabled** | **bool** | Enabled flag | [optional] [default to True]
**always_expose_tools** | **bool** | Whether every tool bypasses Tool Search and remains visible | 

## Example

```python
from azentspublicclient.models.personal_toolkit_create_request import PersonalToolkitCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalToolkitCreateRequest from a JSON string
personal_toolkit_create_request_instance = PersonalToolkitCreateRequest.from_json(json)
# print the JSON string representation of the object
print(PersonalToolkitCreateRequest.to_json())

# convert the object into a dict
personal_toolkit_create_request_dict = personal_toolkit_create_request_instance.to_dict()
# create an instance of PersonalToolkitCreateRequest from a dict
personal_toolkit_create_request_from_dict = PersonalToolkitCreateRequest.from_dict(personal_toolkit_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


