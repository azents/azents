# RuntimeWebUpdateRequest

Update service metadata using omission for unchanged fields.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** |  | 
**label** | **str** |  | [optional] 
**selected_duration_seconds** | **int** |  | [optional] 
**operation_key** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_update_request import RuntimeWebUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebUpdateRequest from a JSON string
runtime_web_update_request_instance = RuntimeWebUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebUpdateRequest.to_json())

# convert the object into a dict
runtime_web_update_request_dict = runtime_web_update_request_instance.to_dict()
# create an instance of RuntimeWebUpdateRequest from a dict
runtime_web_update_request_from_dict = RuntimeWebUpdateRequest.from_dict(runtime_web_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


