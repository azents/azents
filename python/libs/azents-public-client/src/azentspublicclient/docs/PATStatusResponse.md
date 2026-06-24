# PATStatusResponse

PAT status response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**registered** | **bool** | Whether PAT is registered |
**github_username** | **str** |  | [optional]
**display_hint** | **str** |  | [optional]
**expires_at** | **datetime** |  | [optional]

## Example

```python
from azentspublicclient.models.pat_status_response import PATStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PATStatusResponse from a JSON string
pat_status_response_instance = PATStatusResponse.from_json(json)
# print the JSON string representation of the object
print(PATStatusResponse.to_json())

# convert the object into a dict
pat_status_response_dict = pat_status_response_instance.to_dict()
# create an instance of PATStatusResponse from a dict
pat_status_response_from_dict = PATStatusResponse.from_dict(pat_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
