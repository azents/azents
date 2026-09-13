# RuntimeWebSeparateInitiateRequest

Start one browser-bound separate-domain exchange.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**endpoint_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_separate_initiate_request import RuntimeWebSeparateInitiateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebSeparateInitiateRequest from a JSON string
runtime_web_separate_initiate_request_instance = RuntimeWebSeparateInitiateRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebSeparateInitiateRequest.to_json())

# convert the object into a dict
runtime_web_separate_initiate_request_dict = runtime_web_separate_initiate_request_instance.to_dict()
# create an instance of RuntimeWebSeparateInitiateRequest from a dict
runtime_web_separate_initiate_request_from_dict = RuntimeWebSeparateInitiateRequest.from_dict(runtime_web_separate_initiate_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


