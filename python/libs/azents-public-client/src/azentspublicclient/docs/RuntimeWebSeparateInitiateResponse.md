# RuntimeWebSeparateInitiateResponse

Main-origin binding state returned without URL credentials.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**initiation_id** | **str** |  | 
**main_binding_secret** | **str** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_separate_initiate_response import RuntimeWebSeparateInitiateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebSeparateInitiateResponse from a JSON string
runtime_web_separate_initiate_response_instance = RuntimeWebSeparateInitiateResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebSeparateInitiateResponse.to_json())

# convert the object into a dict
runtime_web_separate_initiate_response_dict = runtime_web_separate_initiate_response_instance.to_dict()
# create an instance of RuntimeWebSeparateInitiateResponse from a dict
runtime_web_separate_initiate_response_from_dict = RuntimeWebSeparateInitiateResponse.from_dict(runtime_web_separate_initiate_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


