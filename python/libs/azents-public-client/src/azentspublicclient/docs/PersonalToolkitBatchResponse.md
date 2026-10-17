# PersonalToolkitBatchResponse

Acknowledged complete atomic save, excluding credential and owner material.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[PersonalToolkitAccessResponse]**](PersonalToolkitAccessResponse.md) |  | 

## Example

```python
from azentspublicclient.models.personal_toolkit_batch_response import PersonalToolkitBatchResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalToolkitBatchResponse from a JSON string
personal_toolkit_batch_response_instance = PersonalToolkitBatchResponse.from_json(json)
# print the JSON string representation of the object
print(PersonalToolkitBatchResponse.to_json())

# convert the object into a dict
personal_toolkit_batch_response_dict = personal_toolkit_batch_response_instance.to_dict()
# create an instance of PersonalToolkitBatchResponse from a dict
personal_toolkit_batch_response_from_dict = PersonalToolkitBatchResponse.from_dict(personal_toolkit_batch_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


