# RuntimeWebSeparateBoundRequest

Prove the exact Main binding after the broker callback.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**initiation_id** | **str** |  | 
**main_binding_secret** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_separate_bound_request import RuntimeWebSeparateBoundRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebSeparateBoundRequest from a JSON string
runtime_web_separate_bound_request_instance = RuntimeWebSeparateBoundRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebSeparateBoundRequest.to_json())

# convert the object into a dict
runtime_web_separate_bound_request_dict = runtime_web_separate_bound_request_instance.to_dict()
# create an instance of RuntimeWebSeparateBoundRequest from a dict
runtime_web_separate_bound_request_from_dict = RuntimeWebSeparateBoundRequest.from_dict(runtime_web_separate_bound_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


